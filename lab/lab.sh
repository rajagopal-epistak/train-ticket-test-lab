#!/usr/bin/env bash
# Stand up, test and tear down the Train-Ticket lab with Datadog monitoring.
# Usage: lab/lab.sh up|test|down
# Inputs are environment variables; lab/README.md lists them. Every step prints PASS <id> or FAIL <id>: <reason>.
set -euo pipefail

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TF_DIR="$REPO/lab/terraform"
NS=train-ticket
DD_NS=datadog
FLAG_FAULTS="F1 F7 F12 F14 F17 F22"
F3_SERVICES="ts-train-service ts-basic-service ts-order-service ts-order-other-service"
AGENT_IMAGE_RE='^(registry\.datadoghq\.com|(eu\.|asia\.)?gcr\.io/datadoghq|public\.ecr\.aws/datadog|datadoghq\.azurecr\.io|(docker\.io/)?datadog)/agent(:|@|$)'
PINNED_KUBECONFIG=""
F22_ON=""

pass() { echo "PASS $1${2:+: $2}"; }
fail() { echo "FAIL $1: $2" >&2; exit 1; }
now() { date +%s; }

# poll SECONDS INTERVAL CMD...: succeeds as soon as CMD does, fails when SECONDS have passed.
poll() {
  local deadline=$(($(now) + $1)) interval=$2
  shift 2
  until "$@"; do
    [ "$(now)" -lt "$deadline" ] || return 1
    sleep "$interval"
  done
}

cleanup() {
  if [ -n "$F22_ON" ]; then "$REPO/lab/fault.sh" off F22 || true; fi
  if [ -n "$PINNED_KUBECONFIG" ]; then rm -f "$PINNED_KUBECONFIG"; fi
}

require_inputs() {
  local v missing=""
  for v in KUBE_CONTEXT LAB_NAME DD_SITE DD_API_KEY DD_APP_KEY APM_HOSTS_BUDGET APM_INGEST_GB_BUDGET; do
    [ -n "${!v:-}" ] || missing="$missing $v"
  done
  [ -z "$missing" ] || fail P0 "missing inputs:$missing"
  [[ "$LAB_NAME" =~ ^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$ ]] || fail P0 "LAB_NAME must be lowercase letters, digits and dashes (max 40)"
  APM_ENABLED="${APM_ENABLED:-true}"
  case "$APM_ENABLED" in true | false) ;; *) fail P0 "APM_ENABLED must be true or false" ;; esac
  pass P0 "inputs"
}

p1_tools() {
  local t
  for t in terraform kubectl helm make curl python3; do
    command -v "$t" >/dev/null || fail P1 "$t not found on PATH"
  done
  terraform version -json | python3 -c '
import json, sys
v = tuple(int(x) for x in json.load(sys.stdin)["terraform_version"].split(".")[:2])
sys.exit(0 if v >= (1, 8) else 1)' || fail P1 "terraform 1.8 or later is required"
  pass P1 "tools"
}

# Every kubectl, helm and Terraform call, including lab/fault.sh, uses a private kubeconfig pinned to KUBE_CONTEXT.
pin_context() {
  PINNED_KUBECONFIG=$(mktemp)
  chmod 600 "$PINNED_KUBECONFIG"
  kubectl config view --minify --flatten --context="$KUBE_CONTEXT" >"$PINNED_KUBECONFIG" 2>/dev/null ||
    fail P2 "context $KUBE_CONTEXT not found in the kubeconfig"
  kubectl --kubeconfig="$PINNED_KUBECONFIG" config use-context "$KUBE_CONTEXT" >/dev/null
  export KUBECONFIG="$PINNED_KUBECONFIG"
}

p2_cluster() {
  local bad
  bad=$(kubectl get nodes -o json | python3 -c '
import json, sys
bad = []
for n in json.load(sys.stdin)["items"]:
    ready = any(c["type"] == "Ready" and c["status"] == "True" for c in n["status"]["conditions"])
    arch = n["metadata"]["labels"].get("kubernetes.io/arch")
    if not ready or arch != "amd64":
        bad.append(f"{n[\"metadata\"][\"name\"]} ready={ready} arch={arch}")
print("; ".join(bad))
sys.exit(1 if bad else 0)') || fail P2 "nodes not usable: $bad"
  kubectl get storageclass -o json | python3 -c '
import json, sys
items = json.load(sys.stdin)["items"]
sys.exit(0 if any((s["metadata"].get("annotations") or {}).get("storageclass.kubernetes.io/is-default-class") == "true" for s in items) else 1)' ||
    fail P2 "no default StorageClass"
  pass P2 "cluster"
}

# dd_call METHOD PATH [JSON]: prints the response body; succeeds on HTTP 2xx. Keys go through curl's stdin config, never argv.
dd_call() {
  local method=$1 path=$2 data=${3:-} out code
  out=$(mktemp)
  code=$(printf 'header = "DD-API-KEY: %s"\nheader = "DD-APPLICATION-KEY: %s"\n' "$DD_API_KEY" "$DD_APP_KEY" |
    curl -sS --max-time 30 -K - -o "$out" -w '%{http_code}' -X "$method" -H 'Content-Type: application/json' \
      ${data:+--data "$data"} "https://api.$DD_SITE$path") || code=000
  cat "$out"
  rm -f "$out"
  [ "${code:0:1}" = 2 ]
}

p3_keys() {
  dd_call GET /api/v1/validate | python3 -c 'import json, sys; sys.exit(0 if json.load(sys.stdin).get("valid") else 1)' ||
    fail P3 "DD_API_KEY is not valid for $DD_SITE"
  dd_call GET "/api/v1/monitor?page_size=1" >/dev/null || fail P3 "DD_APP_KEY cannot read monitors on $DD_SITE"
  pass P3 "Datadog keys"
}

# ns_owner NAMESPACE: prints the namespace's lab label, "none" if unlabelled, "absent" if it doesn't exist.
ns_owner() {
  kubectl get namespace "$1" >/dev/null 2>&1 || {
    echo absent
    return
  }
  local owner
  owner=$(kubectl get namespace "$1" -o jsonpath='{.metadata.labels.lab}')
  echo "${owner:-none}"
}

p4_namespace() {
  local owner
  owner=$(ns_owner "$NS")
  case "$owner" in
    absent | "$LAB_NAME") pass P4 "namespace $NS" ;;
    *) fail P4 "namespace $NS exists and belongs to lab '$owner', not '$LAB_NAME'" ;;
  esac
}

tf() {
  local stage=$1
  shift
  terraform -chdir="$TF_DIR/$stage" "$@"
}

tf_ready() {
  tf "$1" init -input=false >/dev/null
  tf "$1" workspace select -or-create "$LAB_NAME" >/dev/null
}

tf_has_state() { [ -n "$(tf "$1" state list 2>/dev/null)" ]; }

# tf_eval STAGE EXPR: evaluates EXPR with terraform console and prints it as JSON.
tf_eval() {
  echo "jsonencode($2)" | tf "$1" console | python3 -c 'import json, sys; print(json.loads(sys.stdin.read()))'
}

export_tf_vars() {
  export TF_VAR_kubeconfig="$KUBECONFIG" TF_VAR_lab_name="$LAB_NAME" TF_VAR_dd_site="$DD_SITE" \
    TF_VAR_apm_enabled="$APM_ENABLED" TF_VAR_apm_hosts_budget="$APM_HOSTS_BUDGET" \
    TF_VAR_apm_ingest_gb_budget="$APM_INGEST_GB_BUDGET" TF_VAR_telemetry_file="$REPO/lab/telemetry.yaml"
}

p6_telemetry() {
  local unknown
  tf_ready lab
  unknown=$(tf_eval lab local.unknown_services) || fail P6 "lab/telemetry.yaml does not parse"
  [ "$unknown" = "[]" ] || fail P6 "lab/telemetry.yaml names unknown deployments: $unknown"
  pass P6 "telemetry switches"
}

foreign_agent_daemonsets() {
  kubectl get daemonsets -A -o json | python3 -c '
import json, re, sys
image = re.compile(sys.argv[1])
for ds in json.load(sys.stdin)["items"]:
    labels = ds["metadata"].get("labels") or {}
    images = [c["image"] for c in ds["spec"]["template"]["spec"]["containers"]]
    if labels.get("agent.datadoghq.com/component") == "agent" or any(image.search(i) for i in images):
        print(ds["metadata"]["namespace"] + "/" + ds["metadata"]["name"])' "$AGENT_IMAGE_RE" | tr '\n' ' '
}

probe_overrides() {
  printf '{"spec":{"nodeName":"%s","tolerations":[{"operator":"Exists"}],"volumes":[{"name":"etc","hostPath":{"path":"/etc","type":"Directory"}}],"containers":[{"name":"%s","image":"docker.io/library/busybox:1.37","stdin":true,"command":["sh","-c","if test -f /host/etc/datadog-agent/datadog.yaml; then echo DATADOG_CONFIG_PRESENT; else echo DATADOG_CONFIG_ABSENT; fi"],"volumeMounts":[{"name":"etc","mountPath":"/host/etc","readOnly":true}]}]}}' "$1" "$2"
}

# Prints the nodes whose OS has the Datadog Agent package config (/etc/datadog-agent/datadog.yaml). Every
# probe pod prints an explicit present/absent marker: kubectl run also returns non-zero for reasons that
# have nothing to do with the file being absent (an image pull failure, a policy denial, a timed-out pod, a
# leftover terminating probe from the last run), and a missing marker must not read as "no Agent" -- that
# is the case D3 exists to prevent -- so it fails P5 instead.
host_agent_nodes() {
  local node pod out found=""
  kubectl create namespace tt-lab-probe --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  kubectl label namespace tt-lab-probe --overwrite pod-security.kubernetes.io/enforce=privileged >/dev/null
  for node in $(kubectl get nodes -o jsonpath='{.items[*].metadata.name}'); do
    pod="probe-$RANDOM"
    out=$(kubectl -n tt-lab-probe run "$pod" --rm -i --restart=Never --quiet --pod-running-timeout=3m \
      --image=docker.io/library/busybox:1.37 --overrides="$(probe_overrides "$node" "$pod")" 2>/dev/null || true)
    case "$out" in
      *DATADOG_CONFIG_PRESENT*) found="$found $node" ;;
      *DATADOG_CONFIG_ABSENT*) ;;
      *)
        kubectl delete namespace tt-lab-probe --wait=false >/dev/null
        fail P5 "host probe on $node produced no result (image pull, a policy denial, a timeout, or a leftover pod)"
        ;;
    esac
  done
  kubectl delete namespace tt-lab-probe --wait=false >/dev/null
  echo "${found# }"
}

# Sets INSTALL_AGENT. An Agent this lab installed is kept; any other Agent, in the cluster or on a node, means skip.
p5_agent() {
  local found owner
  tf_ready datadog
  if tf_has_state datadog; then
    INSTALL_AGENT=true
    pass P5 "Agent installed by this lab; keeping it"
    return
  fi
  found=$(foreign_agent_daemonsets)
  if [ -n "${found// /}" ]; then
    INSTALL_AGENT=false
    pass P5 "Agent DaemonSet found (${found% }); skipping install; APM injection, log collection and state metrics unverified"
    return
  fi
  found=$(host_agent_nodes)
  if [ -n "$found" ]; then
    INSTALL_AGENT=false
    pass P5 "Agent installed on node OS ($found); skipping install; APM injection, log collection and state metrics unverified"
    return
  fi
  owner=$(ns_owner "$DD_NS")
  case "$owner" in
    absent | "$LAB_NAME") ;;
    *) fail P5 "namespace $DD_NS exists and is not this lab's; not installing into it" ;;
  esac
  INSTALL_AGENT=true
  pass P5 "no Agent found; installing"
}

# wait_for KIND/NAME NAMESPACE SECONDS: waits until the object exists (the Operator creates the Agent objects asynchronously).
wait_for() { poll "$3" 10 kubectl -n "$2" get "$1" >/dev/null 2>&1; }

stage_datadog() {
  kubectl create namespace "$DD_NS" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  kubectl label namespace "$DD_NS" --overwrite lab="$LAB_NAME" pod-security.kubernetes.io/enforce=privileged >/dev/null
  kubectl -n "$DD_NS" create secret generic datadog-secret \
    --from-env-file=<(printf 'api-key=%s\napp-key=%s\n' "$DD_API_KEY" "$DD_APP_KEY") \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  tf datadog apply -input=false -auto-approve || fail S1 "terraform apply of stage datadog failed"
  pass S1 "Datadog Operator and Agent applied"
  wait_for deployment/datadog-cluster-agent "$DD_NS" 600 || fail G1 "Cluster Agent deployment not created"
  kubectl -n "$DD_NS" rollout status deployment/datadog-cluster-agent --timeout=600s >/dev/null || fail G1 "Cluster Agent not available"
  wait_for daemonset/datadog-agent "$DD_NS" 600 || fail G1 "Agent DaemonSet not created"
  kubectl -n "$DD_NS" rollout status daemonset/datadog-agent --timeout=600s >/dev/null || fail G1 "Agent DaemonSet not ready on every node"
  poll 300 10 kubectl get mutatingwebhookconfiguration datadog-webhook >/dev/null 2>&1 || fail G1 "admission webhook datadog-webhook missing"
  pass G1 "Agent running; admission webhook present"
}

# Prints the lab faults that are on right now (F3 and F15 by their patches, the rest by the flag config).
faults_on() {
  local svc on=""
  kubectl -n "$NS" get configmap flagd-config -o jsonpath='{.data.flags\.yaml}' 2>/dev/null | awk '
    /^  tt-feat-[0-9]+:$/ { key = $1; sub(":", "", key) }
    /defaultVariant:/ && key { v = $2; gsub(/"/, "", v); if (v == "on") print key; key = "" }' |
    while read -r key; do
      n=$((10#${key#tt-feat-}))
      case " $FLAG_FAULTS " in *" F$n "*) printf 'F%s ' "$n" ;; esac
    done
  for svc in $F3_SERVICES; do
    if [ -n "$(kubectl -n "$NS" get deployment "$svc" -o jsonpath='{.spec.template.spec.containers[0].command}' 2>/dev/null)" ]; then
      on="F3 "
    fi
  done
  printf '%s' "$on"
  if [ -n "$(kubectl -n "$NS" get deployment ts-ui-dashboard -o jsonpath='{.spec.template.spec.volumes[?(@.name=="f15-nginx")].name}' 2>/dev/null)" ]; then
    printf 'F15 '
  fi
}

# Terraform owns the Deployments and the flag config; fault.sh patches both. Switch faults off first, so a re-run
# restores the baseline instead of leaving half a patch (e.g. F3's JVM command with the original memory limit).
faults_off() {
  local f active
  active=$(faults_on)
  for f in $active; do
    NAMESPACE="$NS" "$REPO/lab/fault.sh" off "$f" >/dev/null || fail S2 "could not switch $f off"
  done
  pass S2 "faults off before apply${active:+ (switched off: $active)}"
}

g2_rollout() {
  if ! kubectl -n "$NS" wait --for=condition=Available deployment --all --timeout=1200s >/dev/null; then
    fail G2 "deployments not available: $(kubectl -n "$NS" get deployments --no-headers | awk '{split($2, r, "/"); if (r[1] != r[2]) printf "%s ", $1}')"
  fi
  local sts
  for sts in $(kubectl -n "$NS" get statefulsets -o jsonpath='{.items[*].metadata.name}'); do
    kubectl -n "$NS" rollout status "statefulset/$sts" --timeout=600s >/dev/null || fail G2 "statefulset $sts not ready"
  done
  pass G2 "all deployments and statefulsets ready"
}

# The mysql chart asks for max_connections=65535, which has been seen not to apply; 29 services share tsdb.
g3_mysql() {
  local pod value
  for pod in tsdb-mysql-0 tsdb-mysql-1 tsdb-mysql-2; do
    value=$(kubectl -n "$NS" exec "$pod" -- mysql -uroot -N -e "SELECT @@max_connections")
    [[ "$value" =~ ^[0-9]+$ ]] || fail G3 "$pod answered '$value' to SELECT @@max_connections"
    if [ "$value" -lt 500 ]; then
      kubectl -n "$NS" exec "$pod" -- mysql -uroot -e "SET GLOBAL max_connections = 500"
      value=$(kubectl -n "$NS" exec "$pod" -- mysql -uroot -N -e "SELECT @@max_connections")
      [ "$value" -ge 500 ] || fail G3 "$pod max_connections is $value"
    fi
  done
  pass G3 "tsdb max_connections >= 500"
}

g4_faults() {
  local f active out
  active=$(faults_on)
  [ -z "$active" ] || fail G4 "faults on after apply: $active"
  for f in $FLAG_FAULTS; do
    out=$(NAMESPACE="$NS" "$REPO/lab/fault.sh" status "$f")
    [[ "$out" == *" false" ]] || fail G4 "flagd serves $out for $f"
  done
  pass G4 "all eight faults off; flagd serves every flag off"
}

sample_pod_injected() {
  kubectl -n "$NS" get pods -l app=ts-basic-service -o jsonpath='{.items[0].spec.initContainers[*].name}' | grep -q datadog
}

g5_apm() {
  if [ "$APM_ENABLED" != true ] || [ "$INSTALL_AGENT" != true ]; then
    pass G5 "skipped (APM off or Agent not ours)"
    return
  fi
  if ! sample_pod_injected; then
    kubectl -n "$NS" rollout restart deployment >/dev/null
    # replicas:1 keeps the old pod Available throughout a restart (maxUnavailable rounds to 0), so
    # `wait --for=condition=Available` returns at once; rollout status on the sampled deployment
    # actually waits for its new pod to replace the old one.
    kubectl -n "$NS" rollout status deployment/ts-basic-service --timeout=1200s >/dev/null || fail G5 "ts-basic-service rollout did not complete"
    sample_pod_injected || fail G5 "ts-basic-service pod has no Datadog init container"
  fi
  pass G5 "APM injected into ts-basic-service"
}

driver_outcomes() {
  [ "$(kubectl -n "$NS" logs deployment/tt-traffic-driver --since=2m 2>/dev/null | grep -c '"evt":"outcome"')" -ge 10 ]
}

g6_driver() {
  poll 300 20 driver_outcomes || fail G6 "traffic driver logged fewer than 10 outcomes in 2 minutes"
  pass G6 "traffic driver running"
}

# metric_seen QUERY: true when the metric query returned a non-empty series over the last 15 minutes.
metric_seen() {
  local to from
  to=$(now)
  from=$((to - 900))
  dd_call GET "/api/v1/query?from=$from&to=$to&query=$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1]))' "$1")" |
    python3 -c 'import json, sys; sys.exit(0 if json.load(sys.stdin).get("series") else 1)'
}

driver_logs_seen() {
  dd_call POST /api/v2/logs/events/search \
    '{"filter":{"query":"kube_namespace:train-ticket service:tt-traffic-driver","from":"now-5m","to":"now"},"page":{"limit":1}}' |
    python3 -c 'import json, sys; sys.exit(0 if json.load(sys.stdin).get("data") else 1)'
}

# Datadog-side checks. With a foreign Agent they only warn: this lab does not control that Agent's features.
g7_datadog() {
  local miss=""
  if [ "$INSTALL_AGENT" = true ]; then
    poll 600 30 metric_seen "sum:kubernetes.pods.running{kube_cluster_name:$LAB_NAME}" || miss="$miss kubernetes-metrics"
  fi
  poll 600 30 driver_logs_seen || miss="$miss driver-logs"
  if [ "$APM_ENABLED" = true ]; then
    poll 600 30 metric_seen "sum:trace.servlet.request.hits{env:$LAB_NAME}.as_count()" || miss="$miss apm-traces"
  fi
  if [ -z "$miss" ]; then
    pass G7 "Datadog receives metrics, driver logs and traces"
  elif [ "$INSTALL_AGENT" = true ]; then
    fail G7 "not arriving in Datadog:$miss"
  else
    echo "WARN G7: not arriving in Datadog:$miss (the Agent is not this lab's)"
  fi
}

cmd_up() {
  require_inputs
  p1_tools
  pin_context
  p2_cluster
  p3_keys
  p4_namespace
  export_tf_vars
  p6_telemetry
  p5_agent
  if [ "$INSTALL_AGENT" = true ]; then stage_datadog; fi
  if [ "$(ns_owner "$NS")" != absent ]; then faults_off; fi
  tf lab apply -input=false -auto-approve || fail S3 "terraform apply of stage lab failed"
  pass S3 "Train-Ticket, flagd, driver and monitors applied"
  g2_rollout
  g3_mysql
  g4_faults
  g5_apm
  g6_driver
  g7_datadog
  echo "UP PASS lab=$LAB_NAME agent=$([ "$INSTALL_AGENT" = true ] && echo installed || echo skipped) apm=$APM_ENABLED"
}

# monitor_group_state ID PATH: the state of the group of monitor ID whose key ends in ":PATH", or "none".
monitor_group_state() {
  dd_call GET "/api/v1/monitor/$1?group_states=all" | python3 -c '
import json, sys
groups = (json.load(sys.stdin).get("state") or {}).get("groups") or {}
print(next((g["status"] for k, g in groups.items() if k.endswith(":" + sys.argv[1])), "none"))' "$2"
}

monitor_state() {
  dd_call GET "/api/v1/monitor/$1" | python3 -c 'import json, sys; print(json.load(sys.stdin).get("overall_state", "Unknown"))'
}

voucher_is() { [ "$(monitor_group_state "$EDGE_ID" /getVoucher)" = "$1" ]; }
voucher_not_alert() { ! voucher_is Alert; }
apm_voucher_alert() { [ -n "$APM_ID" ] && [ "$(monitor_state "$APM_ID")" = Alert ]; }

all_states() {
  local key
  for key in $(echo "$MONITOR_IDS" | python3 -c 'import json, sys; print(" ".join(sorted(json.load(sys.stdin))))'); do
    printf '%s=%s ' "$key" "$(monitor_state "$(monitor_id "$key")")"
  done
}

monitor_id() { echo "$MONITOR_IDS" | python3 -c 'import json, sys; print(json.load(sys.stdin).get(sys.argv[1], ""))' "$1"; }

cmd_test() {
  local t_on t_alert t_off t_ok t_apm="" before after apm_note
  require_inputs
  pin_context
  export_tf_vars
  tf_ready datadog
  tf_ready lab
  [ "$(tf_eval lab 'contains(local.logs_off, "tt-traffic-driver")')" = false ] ||
    fail T0 "tt-traffic-driver is in logs_off; the edge monitors read its logs"
  MONITOR_IDS=$(tf lab output -json monitor_ids)
  EDGE_ID=$(monitor_id edge_5xx)
  APM_ID=$(monitor_id voucher_errors)
  [ -n "$EDGE_ID" ] || fail T0 "no edge_5xx monitor in the lab state; run up first"
  pass T0 "monitors found"

  poll 1200 30 voucher_not_alert || fail T1 "edge 5xx on /getVoucher is already alerting before the test"
  before=$(all_states)
  pass T1 "baseline: $before"

  F22_ON=1
  NAMESPACE="$NS" "$REPO/lab/fault.sh" on F22 | grep -q '^tt-feat-22 true$' || fail T2 "flagd does not serve tt-feat-22 on"
  t_on=$(now)
  pass T2 "F22 on"

  local deadline=$((t_on + 900))
  t_alert=""
  while [ "$(now)" -lt "$deadline" ]; do
    if [ -z "$t_apm" ] && apm_voucher_alert; then t_apm=$(now); fi
    if voucher_is Alert; then
      t_alert=$(now)
      break
    fi
    sleep 30
  done

  NAMESPACE="$NS" "$REPO/lab/fault.sh" off F22 | grep -q '^tt-feat-22 false$' || fail T4 "flagd does not serve tt-feat-22 off"
  F22_ON=""
  t_off=$(now)
  [ -n "$t_alert" ] || fail T3 "edge 5xx on /getVoucher did not alert within 15 minutes (F22 switched off again)"
  pass T3 "edge 5xx on /getVoucher alerted after $((t_alert - t_on)) s"

  poll 900 30 voucher_is OK || fail T4 "edge 5xx on /getVoucher did not recover within 15 minutes"
  t_ok=$(now)
  pass T4 "recovered $((t_ok - t_off)) s after F22 off"

  after=$(all_states)
  if [ -z "$APM_ID" ]; then
    apm_note="off (APM_ENABLED=false)"
  elif [ -n "$t_apm" ]; then
    apm_note="alerted after $((t_apm - t_on)) s"
  elif tf_has_state datadog; then
    apm_note="did not alert"
  else
    apm_note="did not alert (APM unsupported: the Agent is not this lab's)"
  fi
  echo "REPORT F22 detect_s=$((t_alert - t_on)) recover_s=$((t_ok - t_off)) apm_error_monitor: $apm_note"
  echo "REPORT monitors before: $before"
  echo "REPORT monitors after:  $after"
  echo "REPORT uncovered: F1 (no generic monitor sees the late refund)"
  echo "TEST PASS lab=$LAB_NAME"
}

# yamls/sw_deploy.yaml is tracked and names the same 46 Deployments as deploy.yaml.sample, so
# `make reset-deploy`'s own `kubectl delete -f yamls -n <ns>` already removes them; no deploy.yaml needed.
native_reset() {
  (cd "$REPO" && make reset-deploy Namespace="$NS") >"${TMPDIR:-/tmp}/lab-native-reset.log" 2>&1 || true
  pass D1 "native make reset-deploy ran (log: ${TMPDIR:-/tmp}/lab-native-reset.log)"
}

ns_absent() { [ "$(ns_owner "$1")" = absent ]; }

monitors_left() {
  dd_call GET "/api/v1/monitor?monitor_tags=lab:$LAB_NAME" | python3 -c 'import json, sys; print(len(json.load(sys.stdin)))'
}

cmd_down() {
  local ours=""
  require_inputs
  pin_context
  export_tf_vars
  if [ "$(ns_owner "$NS")" = "$LAB_NAME" ]; then native_reset; else pass D1 "namespace $NS not present; native reset skipped"; fi
  tf_ready lab
  tf lab destroy -input=false -auto-approve || fail D2 "terraform destroy of stage lab failed"
  pass D2 "stage lab destroyed"
  tf_ready datadog
  if tf_has_state datadog; then
    ours=1
    tf datadog destroy -input=false -auto-approve || fail D3 "terraform destroy of stage datadog failed"
    # The Cluster Agent creates this webhook with no labels and no ownerReferences, and only deletes it when
    # mutation is disabled, never on shutdown. Neither the Operator's cleanup nor the Helm chart removes it either.
    kubectl delete mutatingwebhookconfiguration datadog-webhook --ignore-not-found >/dev/null
    if [ "$(ns_owner "$DD_NS")" = "$LAB_NAME" ]; then kubectl delete namespace "$DD_NS" --timeout=600s >/dev/null; fi
    pass D3 "stage datadog destroyed"
  else
    pass D3 "Agent not installed by this lab; left alone"
  fi
  poll 600 15 ns_absent "$NS" || fail D4 "namespace $NS still present"
  if [ -n "$ours" ]; then
    [ "$(ns_owner "$DD_NS")" = absent ] || fail D4 "namespace $DD_NS still present"
    ! kubectl get mutatingwebhookconfiguration datadog-webhook >/dev/null 2>&1 || fail D4 "webhook datadog-webhook still present"
  fi
  [ "$(monitors_left)" = 0 ] || fail D4 "monitors tagged lab:$LAB_NAME remain"
  pass D4 "lab $LAB_NAME removed"
  echo "DOWN PASS lab=$LAB_NAME"
}

main() {
  trap cleanup EXIT
  case "${1:-}" in
    up) cmd_up ;;
    test) cmd_test ;;
    down) cmd_down ;;
    *)
      echo "usage: lab/lab.sh up|test|down" >&2
      exit 2
      ;;
  esac
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
