#!/usr/bin/env bash
# Switch the lab's injected faults on or off in the running cluster.
# Usage: lab/fault.sh on|off|status F1|F3|F7|F12|F14|F15|F17|F22
# Env:   NAMESPACE (default train-ticket). kubectl must point at the lab cluster.
set -euo pipefail

NS="${NAMESPACE:-train-ticket}"
NGINX_CONF=/usr/local/openresty/nginx/conf/nginx.conf
# The services the original F3 misconfigured. Every one of their images keeps its jar at /app/<service>-1.0.jar.
F3_SERVICES="ts-train-service ts-basic-service ts-order-service ts-order-other-service"
F3_MEMORY_LIMIT=640Mi
BASE_MEMORY_LIMIT=2000Mi

usage() {
  echo "usage: lab/fault.sh on|off|status F1|F3|F7|F12|F14|F15|F17|F22" >&2
  exit 2
}

k() { kubectl -n "$NS" "$@"; }

flag_key() { printf 'tt-feat-%02d' "${1#F}"; }

# stdin: flagd flags.yaml. Sets defaultVariant of flag $1 to $2 (on|off); every other flag is left alone.
flip_flag_text() {
  sed "/^  $1:\$/,/defaultVariant:/ s/defaultVariant: \"[a-z]*\"/defaultVariant: \"$2\"/"
}

# stdin: nginx.conf. Adds the F15 body limit as the first line of the /api/v1/ location.
# 300 B lets plain bookings (238 B) through and refuses bookings with food (330 B) or consign (335 B).
limit_body_text() {
  awk '{ print } index($0, "location /api/v1/ {") { print "      client_max_body_size 300;" }'
}

# The F3 container command: a JVM heap larger than the container's memory limit.
# It replaces `command`, so it overrides both CMD- and ENTRYPOINT-style images.
f3_command() { printf '["java","-Xms1g","-Xmx1g","-jar","/app/%s-1.0.jar"]' "$1"; }

# Prints true|false: the value flagd serves right now, read over OFREP from inside the namespace.
flag_served() {
  k run "flagcheck-$RANDOM" --rm -i --restart=Never --quiet --pod-running-timeout=5m --image=python:3.12-slim --command -- python -c \
    "import json, urllib.request; req = urllib.request.Request('http://flagd:8016/ofrep/v1/evaluate/flags/$1', data=b'{\"context\":{}}', headers={'Content-Type': 'application/json'}); print(str(json.load(urllib.request.urlopen(req))['value']).lower())" \
    | grep -E '^(true|false)$'
}

set_flag() {
  local tmp
  tmp=$(mktemp)
  k get configmap flagd-config -o jsonpath='{.data.flags\.yaml}' | flip_flag_text "$1" "$2" > "$tmp"
  k create configmap flagd-config --from-file=flags.yaml="$tmp" --dry-run=client -o yaml | k apply -f -
  rm -f "$tmp"
  k rollout restart deployment/flagd
  k rollout status deployment/flagd --timeout=120s
}

flag_fault() {
  local action="$1" key="$2" want got
  case "$action" in
    on) set_flag "$key" on; want=true ;;
    off) set_flag "$key" off; want=false ;;
    status) echo "$key $(flag_served "$key")"; return ;;
  esac
  got=$(flag_served "$key")
  if [ "$got" != "$want" ]; then
    echo "flagd serves $key=$got, expected $want" >&2
    exit 1
  fi
  echo "$key $got"
}

f3() {
  local svc
  for svc in $F3_SERVICES; do
    case "$1" in
      on)
        k patch deployment "$svc" --type=json -p "[
          {\"op\":\"add\",\"path\":\"/spec/template/spec/containers/0/command\",\"value\":$(f3_command "$svc")},
          {\"op\":\"replace\",\"path\":\"/spec/template/spec/containers/0/resources/limits/memory\",\"value\":\"$F3_MEMORY_LIMIT\"}]" ;;
      off)
        if [ -n "$(k get deployment "$svc" -o jsonpath='{.spec.template.spec.containers[0].command}')" ]; then
          k patch deployment "$svc" --type=json -p "[
            {\"op\":\"remove\",\"path\":\"/spec/template/spec/containers/0/command\"},
            {\"op\":\"replace\",\"path\":\"/spec/template/spec/containers/0/resources/limits/memory\",\"value\":\"$BASE_MEMORY_LIMIT\"}]"
        fi ;;
    esac
  done
  if [ "$1" != status ]; then
    for svc in $F3_SERVICES; do
      k rollout status deployment/"$svc" --timeout=300s || echo "$svc not ready after 300s"
    done
  fi
  for svc in $F3_SERVICES; do
    k get deployment "$svc" -o jsonpath="F3 $svc command={.spec.template.spec.containers[0].command} memory={.spec.template.spec.containers[0].resources.limits.memory}{\"\n\"}"
    k get pods -l app="$svc" -o jsonpath='{range .items[*]}{.metadata.name} restarts={.status.containerStatuses[0].restartCount} last={.status.containerStatuses[0].lastState.terminated.reason}{"\n"}{end}'
  done
}

f15_lines() { k exec deployment/ts-ui-dashboard -- grep -c client_max_body_size "$NGINX_CONF" || true; }

f15() {
  case "$1" in
    on)
      if [ "$(f15_lines)" = "0" ]; then
        local tmp
        tmp=$(mktemp)
        k exec deployment/ts-ui-dashboard -- cat "$NGINX_CONF" | limit_body_text > "$tmp"
        k create configmap ts-ui-dashboard-f15 --from-file=nginx.conf="$tmp" --dry-run=client -o yaml | k apply -f -
        rm -f "$tmp"
        k patch deployment ts-ui-dashboard --type=strategic -p '{"spec":{"template":{"spec":{
          "volumes":[{"name":"f15-nginx","configMap":{"name":"ts-ui-dashboard-f15"}}],
          "containers":[{"name":"ts-ui-dashboard","volumeMounts":[{"name":"f15-nginx","mountPath":"'"$NGINX_CONF"'","subPath":"nginx.conf"}]}]}}}}'
        k rollout status deployment/ts-ui-dashboard --timeout=300s
      fi ;;
    off)
      k patch deployment ts-ui-dashboard --type=strategic -p '{"spec":{"template":{"spec":{
        "volumes":[{"name":"f15-nginx","$patch":"delete"}],
        "containers":[{"name":"ts-ui-dashboard","volumeMounts":[{"mountPath":"'"$NGINX_CONF"'","$patch":"delete"}]}]}}}}'
      k rollout status deployment/ts-ui-dashboard --timeout=300s
      k delete configmap ts-ui-dashboard-f15 --ignore-not-found ;;
  esac
  echo "F15 client_max_body_size lines: $(f15_lines)"
}

main() {
  [ $# -eq 2 ] || usage
  case "$1" in on|off|status) ;; *) usage ;; esac
  case "$2" in
    F1|F7|F12|F14|F17|F22) flag_fault "$1" "$(flag_key "$2")" ;;
    F3) f3 "$1" ;;
    F15) f15 "$1" ;;
    *) usage ;;
  esac
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
