# Lab deploy: Terraform setup, Datadog monitoring and a fault test

**Date:** 2026-09-26. **Branch:** `lab/deploy`, from `master` at `a4c1abce` (easy-faults merged).

## Goal

The owner hands this deliverable to an agent, and the agent runs it. It needs no reasoning, and it gives the same result every time.
- `lab/lab.sh up` stands the lab up on any x86_64 Kubernetes cluster:
  - the Datadog Agent, unless one is already present;
  - Train-Ticket with the eight lab faults, flagd and the traffic driver;
  - fault-agnostic Datadog monitors.
- `lab/lab.sh test` injects F22 and proves a monitor catches it.
- `lab/lab.sh down` removes everything the lab created.

The script owns the idempotency, the live-state checks and the teardown. The agent only runs it and reports.

## Decisions (owner, 2026-09-26)

| # | Decision |
|---|---|
| D1 | The deliverable is a script the agent runs. It replaces the agent-read runbook `lab/DEPLOYER.md`, which this branch deletes. |
| D2 | Everything runs as Kubernetes workloads in namespaces. Nothing is installed on a node's OS. |
| D3 | Install the Datadog Agent through the Datadog Operator (Datadog's recommended method). Skip the install when an Agent is already present: one in the cluster that this lab did not create, or one installed on a node's OS. |
| D4 | Terraform for everything with lasting state; a thin `lab/lab.sh` wrapper for checks, the Agent decision and sequencing; the existing `lab/fault.sh` for faults. |
| D5 | APM on, via Single Step Instrumentation (SSI), scoped to namespace `train-ticket`. One input, `APM_ENABLED`, turns off both SSI and the APM monitors. |
| D6 | Monitors are fault-agnostic (golden signals, pod health, business and data checks, budget guards). There are no per-fault oracle monitors. |
| D7 | No notification handle on any monitor. Tests read monitor state through the API. |
| D8 | The test fault is F22. |
| D9 | The work lives on the `lab/deploy` branch, in the worktree `~/Documents/barath/work/train-ticket-test-lab-deploy`. |
| D10 | The F22 fault is unchanged (the voucher lookup names a missing column, so `/getVoucher` returns HTTP 500). What changed is the test's pass signal: the driver's edge-5xx monitor for `/getVoucher`. The APM error-rate monitor on the voucher is reported, not required. |
| D11 | Teardown respects the repo's native commands. `down` runs `make reset-deploy Namespace=train-ticket` first. Terraform then removes only what the native reset leaves behind. |
| D12 | Log and APM transport can be switched off per service in `lab/telemetry.yaml`. Logs are collected from the whole `train-ticket` namespace unless switched off. |
| D13 | `lab/README.md` holds every instruction needed to run the lab: prerequisites, inputs, commands, per-service switches, teardown and troubleshooting. |

**Why the pass signal moved (D10):**
- Datadog's Python tracer lists Tornado as *"Automatic: no"*: the patch must run before Tornado is imported. It is unproven that SSI's injection meets that for `ts-voucher-service`.
- The spec sets `DD_TRACE_TORNADO_ENABLED=true` through SSI's `ddTraceConfigs`. That is inferred from ddtrace's convention for integrations that are off by default, not quoted from the docs.
- The edge monitor fires whenever F22 is on, whether or not APM traces exist.

## Layout

```
lab/
  lab.sh                 # up | test | down
  fault.sh               # unchanged
  terraform/
    datadog/             # stage 1 (only when installing the Agent): Operator chart + DatadogAgent via a local chart
      agent-chart/       #   one template: the DatadogAgent resource, filled from Terraform values
    lab/                 # stage 2: namespace, 4 infra charts, 117 app objects, flagd, driver, monitors
  telemetry.yaml         # per-service log/APM switches (D12), committed with empty lists
  tests/                 # offline tests (see Testing)
lab/README.md            # the full run guide (D13); replaces the DEPLOYER.md pointer
```

Why the DatadogAgent is a local chart and not `kubernetes_manifest`: the manifest resource *"requires API access during planning time … and thus cannot be created in the same apply operation"* as its CRD. A `helm_release` checks the CRD only when it applies. So an Operator release followed by an agent release (with `depends_on`) works in one apply.

## Inputs

All inputs come from environment variables, so keys never appear in argv, files or Terraform state.

| Variable | Required | Example | Use |
|---|---|---|---|
| `KUBE_CONTEXT` | yes | `lab-ctx` | the only context used; every `kubectl` and provider call passes it explicitly |
| `LAB_NAME` | yes | `tt-lab-1` | the Datadog cluster name, the `env` tag, the `lab:` tag, the monitor-name prefix and the Terraform workspace name |
| `DD_SITE` | yes | `datadoghq.eu` | Agent `global.site`; provider `api_url = https://api.<DD_SITE>/` |
| `DD_API_KEY`, `DD_APP_KEY` | yes | none | read by the Datadog provider from the environment; put in the Agent Secret by the wrapper |
| `APM_HOSTS_BUDGET` | yes | `4` | threshold of the APM-host budget monitor |
| `APM_INGEST_GB_BUDGET` | yes | `150` | monthly ingested-span GB budget; the monitor alerts on a daily share (budget ÷ 30) |
| `APM_ENABLED` | no, default `true` | `false` | turns off SSI and the APM monitors |

**Tools on the runner:**
- `terraform` 1.8 or later (1.16.x recommended), for provider-defined functions;
- `kubectl`, `curl`, `python3`;
- no Helm CLI.

**Pinned providers:**
- `hashicorp/helm ~> 3.3`, using v3 syntax (`kubernetes = { config_path, config_context }`, `set = [{name, value}]`);
- `hashicorp/kubernetes ~> 3.2`;
- `DataDog/datadog ~> 4.22`.

**Other pins:** Operator chart `2.27.0`; Agent and Cluster Agent `7.83.3`.

**State:** local, one workspace per `LAB_NAME` (`terraform workspace select -or-create`), git-ignored. Losing the state means a manual teardown.

**Context pinning:**
- The wrapper writes a minified kubeconfig for `KUBE_CONTEXT` to a temp file (`kubectl config view --minify --flatten --context=…`, mode 600, deleted by an exit trap) and exports `KUBECONFIG` to it.
- That makes every `kubectl` call, including the unchanged `fault.sh`, and both providers' `config_path` target that one context. The user's own current-context is left alone.

## `up`

Each numbered step prints `PASS <id>` or `FAIL <id>: <reason>`. The first FAIL stops the run with exit 1. Running `up` again is safe.

### Preflight

- **P1:** the tools are present, and `terraform version` ≥ 1.8.
- **P2:** the context exists. Every node is Ready and `amd64`. The cluster has a default StorageClass.
- **P3:** `GET /api/v1/validate` with `DD-API-KEY` returns `{"valid": true}`. The app key is checked with `GET /api/v1/monitor?page_size=1`; Datadog has no app-key validation endpoint, so a 200 counts as valid.
- **P4:** namespace `train-ticket` is absent, or it carries the label `lab=<LAB_NAME>`. Never adopt a stranger's namespace.
- **P6:** `lab/telemetry.yaml` parses and names only known Deployments (see Per-service telemetry switches). This runs before P5 so a typo fails fast; the id is kept stable for the README.

### Agent decision (P5)

`install_agent=true` if the stage-1 state for this workspace is non-empty, because an Agent this lab installed is always kept. Otherwise it is true only if none of the following finds an Agent:
1. **A foreign DaemonSet in the cluster:** any DaemonSet in any namespace labelled `agent.datadoghq.com/component=agent`, or running an image from an official Agent repository: `registry.datadoghq.com`, `gcr.io/datadoghq`, `eu.gcr.io/datadoghq`, `asia.gcr.io/datadoghq`, `public.ecr.aws/datadog`, `datadoghq.azurecr.io`, or `docker.io/datadog` (repository `agent`).
2. **A host install:**
   - For each node, a short-lived pod (`docker.io/library/busybox`, pinned `nodeName`, `hostPath /etc/datadog-agent` read-only) runs `test -f /host/etc/datadog-agent/datadog.yaml`. That is the documented config path of the Linux package.
   - The probe pods run in a temporary namespace `tt-lab-probe` labelled `pod-security.kubernetes.io/enforce=privileged`. It is deleted afterwards.

When the install is skipped, the wrapper prints which features it could not verify: APM injection for `train-ticket`, log collection and Kubernetes state metrics. The APM monitors may then sit at No Data.

### Stage 1: `lab/terraform/datadog` (only when `install_agent`)

The wrapper first creates namespace `datadog` with the labels `lab=<LAB_NAME>` and `pod-security.kubernetes.io/enforce=privileged`. It then applies Secret `datadog-secret` with keys `api-key` and `app-key`: `kubectl create secret … --from-env-file=<(…) --dry-run=client -o yaml | kubectl apply -f -`, with the keys never in argv.

Terraform:
- `helm_release.operator`: chart `datadog-operator` `2.27.0` from `https://helm.datadoghq.com`, namespace `datadog`. It installs the CRDs by default (`installCRDs: true`).
- `helm_release.agent`: the local `agent-chart`, `depends_on` the Operator. It renders:

```yaml
apiVersion: datadoghq.com/v2alpha1
kind: DatadogAgent
metadata: {name: datadog, namespace: datadog}
spec:
  global:
    clusterName: <LAB_NAME>
    site: <DD_SITE>
    tags: ["env:<LAB_NAME>", "lab:<LAB_NAME>"]
    credentials:
      apiSecret: {secretName: datadog-secret, keyName: api-key}
      appSecret: {secretName: datadog-secret, keyName: app-key}
  features:
    apm:
      enabled: <APM_ENABLED>
      instrumentation:
        enabled: <APM_ENABLED>
        targets:
          - name: train-ticket
            namespaceSelector: {matchNames: [train-ticket]}
            ddTraceVersions: {java: "1", python: "4"}
            ddTraceConfigs:
              - name: DD_SERVICE
                valueFrom: {fieldRef: {fieldPath: "metadata.labels['app']"}}   # every pod has app=<deployment>
              - {name: DD_ENV, value: <LAB_NAME>}
              - {name: DD_TRACE_TORNADO_ENABLED, value: "true"}                 # inferred; see D10
    logCollection: {enabled: true, containerCollectAll: true}
    kubeStateMetricsCore: {enabled: true}
  override:
    nodeAgent:
      image: {tag: "7.83.3"}
      env:
        - {name: DD_CONTAINER_EXCLUDE_LOGS, value: "kube_namespace:.*"}
        - {name: DD_CONTAINER_INCLUDE_LOGS, value: "kube_namespace:train-ticket"}
    clusterAgent:
      image: {tag: "7.83.3"}
```

**Gate G1:**
- The Cluster Agent Deployment is Available.
- The Agent DaemonSet is ready on every schedulable node.
- MutatingWebhookConfiguration `datadog-webhook` exists. Pods created before it exists are not instrumented, which is why stage 2 waits for this gate.

### Stage 2: `lab/terraform/lab`

- `kubernetes_namespace_v1.train_ticket`, labelled `lab=<LAB_NAME>`. Every other resource depends on it, so `destroy` deletes it last, and that removes the MySQL PVCs too.
- Four `helm_release` resources from the repo's local charts, using the same values `make deploy` uses (`hack/deploy/utils.sh`):
  - `nacosdb` (mysql chart: user `nacos`, database `nacos`);
  - `nacos` (db host `nacosdb-mysql-leader`), depending on `nacosdb`;
  - `rabbitmq`;
  - `tsdb` (mysql chart: user `ts`, database `ts`).

  They use `wait = true` and `timeout = 900`.
- `kubernetes_manifest` for every document in:
  - `yamls/secret.yaml` (27 Secrets, tracked, host `tsdb-mysql-leader`);
  - `yamls/svc.yaml` (44 Services);
  - `yamls/deploy.yaml.sample` (46 Deployments; `make deploy`'s `sed` is a no-op, so the sample is the deployed file).

  Each set is decoded with `provider::kubernetes::manifest_decode_multi`, keyed `"<kind>/<name>"`, and given `metadata.namespace = "train-ticket"`. The resources have no `wait` block; the wrapper's gates wait instead.
- flagd:
  - ConfigMap `flagd-config` from `templates/flagd-config.yaml`;
  - Deployment and Service from `deployment/lab/flagd.yaml`.
- The driver, from `deployment/lab/traffic-driver.yaml`.
- The monitors (next section). APM monitors have `count = APM_ENABLED ? 1 : 0`.
- Per-service switches from `lab/telemetry.yaml` (next subsection), merged into the decoded Deployment manifests before they reach `kubernetes_manifest`.

### Per-service telemetry switches (`lab/telemetry.yaml`)

```yaml
# Deployment names whose telemetry transport is switched off. Edit, then run `lab/lab.sh up` again.
logs_off: []   # e.g. [ts-news-service]
apm_off: []    # e.g. [tt-traffic-driver]
```

- **`logs_off`:** adds the pod annotation `ad.datadoghq.com/logs_exclude: "true"`. Datadog documents it: *"Excludes log collection from the entire pod"* (Agent v7.45+).
- **`apm_off`:** adds the pod label `admission.datadoghq.com/enabled: "false"`, Datadog's documented way to *"Remove instrumentation for specific services"*.
- **Scope:** both are pod-template changes, so Kubernetes rolls the affected Deployments on the next `up`. Both work with an Agent this lab did not install, because they live on the pods.
- **Validation (P6):** every name must be one of the 46 Train-Ticket Deployments, `tt-traffic-driver` or `flagd`. An unknown name fails `up` before any apply.
- **Global switch:** `APM_ENABLED=false` still turns APM off everywhere. `apm_off` is for single services.
- **Guard:** `test` refuses to run while `tt-traffic-driver` is in `logs_off`, because the edge monitors read the driver's logs.

### Gates after stage 2

- **G2:** `kubectl rollout status` for every Deployment and StatefulSet in `train-ticket`, with a 20 min budget. A FAIL names the stuck object and shows its last events.
- **G3:** on each `tsdb-mysql-N`, `SELECT @@max_connections` returns at least 500. If lower, run `SET GLOBAL max_connections = 500` and read it again. The value does not survive a MySQL restart, which is why every `up` repeats this. The chart's `65535` has been seen not to apply.
- **G4:** `lab/fault.sh status` for each of the eight faults reports off.
- **G5** (APM on and Agent installed by us): pod `ts-basic-service` has the SSI injection init container. If it doesn't, run `kubectl rollout restart deploy -n train-ticket` once and check again.
- **G6:** the driver has logged at least 10 `"evt": "outcome"` lines in the last 2 minutes.
- **G7 (Datadog side;** polls up to 10 min; each check skipped when not applicable):
  1. when the Agent is ours, hosts with `kube_cluster_name:<LAB_NAME>` report, via `GET /api/v1/hosts?filter=`;
  2. a logs search for `service:tt-traffic-driver` over 5 minutes is non-empty;
  3. with APM on, `sum:trace.servlet.request.hits{env:<LAB_NAME>}` is above 0 over 10 minutes.

## Monitors

In the queries, `<L>` stands for `LAB_NAME`, and `<k8s scope>` and `<log scope>` are the scopes listed below.

- **Names:** `[<LAB_NAME>] …`.
- **Tags:** `lab:<LAB_NAME>`, `managed-by:terraform`.
- **Scope:** `env:<LAB_NAME>` for APM; `kube_cluster_name:<LAB_NAME>,kube_namespace:train-ticket` for Kubernetes; `kube_namespace:train-ticket service:tt-traffic-driver` for logs.
- **Settings:** `require_full_window = false` (the traffic is sparse), `notify_no_data = false`, no `@` handle.
- **Types:** metric monitors use `type = "query alert"`, the type the API spec maps the metric category to. Log monitors use `"log alert"`.

| Monitor | Query (thresholds are initial and get tuned after the first baseline) | Expected to catch |
|---|---|---|
| Java p95 latency by service (APM) | `percentile(last_10m):p95:trace.servlet.request{env:<L>} by {service} > 2` | F7, and F1's cancel path if its latency shows |
| Voucher p95 latency (APM) | `percentile(last_10m):p95:trace.tornado.request{env:<L>} by {service} > 2` | F17 |
| Java error rate by service (APM) | `sum(last_10m):sum:trace.servlet.request.errors{env:<L>} by {service}.as_count() / sum:trace.servlet.request.hits{env:<L>} by {service}.as_count() > 0.1` | F7 |
| Voucher error rate (APM) | the same over `trace.tornado.request.*` | F22 (reported, not the pass signal) |
| OOMKilled by deployment | `max(last_10m):max:kubernetes.containers.state.terminated{<k8s scope>,reason:oomkilled} by {kube_deployment} >= 1` | F3 |
| Restarts by deployment | `change(max(last_10m),last_10m):sum:kubernetes.containers.restarts{<k8s scope>} by {kube_deployment} > 2` | F3 |
| Edge 5xx by path (driver) | `logs("<log scope> @evt:outcome (@http_status:500 OR @http_status:502 OR @http_status:503 OR @http_status:504)").index("*").rollup("count").by("@path").last("10m") > 2` | F7, F22 (the test's pass signal) |
| Edge 4xx by path (driver) | the same with `@http_status:400 OR 401 OR 403 OR 404 OR 413`, `> 5` | F15 |
| Business rejections by path (driver) | `logs("<log scope> @evt:outcome @tt_status:0").index("*").rollup("count").by("@path").last("10m") > 20` | F12 |
| Fare anomaly (driver) | `logs("<log scope> @evt:fare_anomaly").index("*").rollup("count").last("10m") > 0` | F14 |
| APM hosts budget | `max(last_1h):max:datadog.estimated_usage.apm_hosts{*} > <APM_HOSTS_BUDGET>` | billing |
| APM ingestion budget | `sum(last_1d):sum:datadog.estimated_usage.apm.ingested_bytes{*}.as_count() > <APM_INGEST_GB_BUDGET × 1e9 / 30>` | billing |

**Inferred, measured on the first run:**
- the `percentile(...)` monitor form for distribution trace metrics;
- exact-match numeric log queries without facets (the docs require a facet only for `<`/`>` comparisons);
- whether the driver's log `service` is `tt-traffic-driver`;
- the daily-sum form of the ingested-bytes budget query.

Datadog validates each query when Terraform creates the monitor, so a malformed query fails `up` at stage 2.

**Expected blind spot:** F1. Its refund lands 8 s after a successful cancel, and no generic signal sees that. The test report lists F1 as uncovered.

## `test` (F22)

1. **Baseline:**
   - `up` must have passed.
   - Wait up to 20 min until the edge-5xx group `@path:/getVoucher` is not in Alert.
   - Record every monitor's `overall_state`.
2. **Inject:** `lab/fault.sh on F22`. It must report the flag as served on.
3. **Detect:** poll `GET /api/v1/monitor/{id}?group_states=all` every 30 s for up to 15 min.
   - **PASS** when the edge-5xx group for `/getVoucher` reaches `Alert`.
   - Record whether the voucher error-rate monitor fired, and when.
4. **Clear:** `lab/fault.sh off F22`. Poll until the group is `OK`, for up to 15 min.
5. **Report:** injection time, alert time, clear time, recovery time, and every monitor whose state changed during the window (possible false positives). If the APM error-rate monitor did not fire, say so, with "APM unsupported" when the Agent install was skipped.

`fault.sh off F22` runs even when detection fails, so a failed test never leaves the fault on.

## `down`

The repo's native teardown runs first (D11). `make reset-deploy` → `hack/deploy/reset.sh` has three gaps, which Terraform covers:
1. It deletes the 46 Deployments only if `yamls/deploy.yaml` exists, because `kubectl delete -f <dir>` skips `.sample` files. `make deploy` generates that file, and it is not git-ignored.
2. It uninstalls the MySQL releases matching `ts-`, so the quickstart's `tsdb` release is missed.
3. It leaves the PVCs behind.

Steps:
1. Generate `yamls/deploy.yaml` with the repo's own function: `source hack/deploy/utils.sh && update_tt_dp_cm nacos rabbitmq`.
2. Run `make reset-deploy Namespace=train-ticket`. Its errors for objects that don't exist (e.g. the skywalking manifests) are expected, and are logged rather than failing the run.
3. Delete the generated `yamls/deploy.yaml`, so the working tree is clean again. The exit trap does this too.
4. `terraform destroy` the `lab` stage. Refresh drops the objects the native reset already removed. Destroy then removes the rest: the `tsdb` release, flagd, the driver, the monitors, and namespace `train-ticket` with its PVCs.
5. If the `datadog` stage state is non-empty:
   - `terraform destroy` it;
   - delete namespace `datadog`, only if it is labelled `lab=<LAB_NAME>`.
6. **Checks:**
   - both namespaces are gone;
   - no monitor tagged `lab:<LAB_NAME>` remains (`GET /api/v1/monitor?monitor_tags=lab:<LAB_NAME>`);
   - when stage 1 was ours, `datadog-webhook` is gone;
   - `git status --porcelain` shows no `deploy.yaml`.

A foreign Agent is never touched.

## README (`lab/README.md`)

The README replaces the `DEPLOYER.md` pointer. It is the complete run guide, and the agent and the owner need nothing else:
1. **What the lab is:** the fault table kept from today's README, plus the monitor list and what each monitor should catch (including F1's gap).
2. **Prerequisites:**
   - the runner's tools and versions, installable with mise;
   - the cluster: x86_64, cluster-admin, a default StorageClass, about 8 CPU / 32 GiB free;
   - the Datadog keys, and the app key's monitor-write permission.
3. **Inputs:** every environment variable, whether it is required, and an example.
4. **Run:**
   - `up`, `test` and `down`, with a sample of the PASS/FAIL output and what each gate checks;
   - a copy-paste block that sets the inputs and runs all three.
5. **Faults:** `lab/fault.sh on|off|status <F>` for the other seven faults, with what each one does and which monitor should notice.
6. **Per-service switches:** how to edit `lab/telemetry.yaml` and re-apply.
7. **Costs:** APM host billing on the monthly high-water mark, the budget monitors, and `APM_ENABLED=false`.
8. **Troubleshooting:** each FAIL id with its likely cause and the command to inspect it. Also a manual teardown for lost Terraform state: the native reset, then deleting the namespaces and the monitors by tag.

## Testing the deliverable

**Offline, in the build:**
- `terraform fmt -check`, and `terraform init -backend=false && terraform validate`, for both stages.
- `lab/tests/test_lab_sh.py`: the wrapper's decision and gate logic, run against stub `kubectl`/`terraform`/`curl` on `PATH`, in the same style as `test_fault_sh.py`. Covered:
  - the Agent decision (own state, foreign DaemonSet by label, foreign by image, host probe hit, none);
  - the P4 namespace guard;
  - `telemetry.yaml` validation (P6), and the `test` guard on driver logs;
  - the G3 `max_connections` fix;
  - the `down` order (deploy.yaml generated, native reset, deploy.yaml removed, then Terraform destroy);
  - the `test` flow, including the clear after a failure.
- The merge logic behind `logs_off`/`apm_off` is checked in `terraform console`, or through a `terraform plan` output against the stub, whichever the plan finds workable offline. It must show the annotation and label on exactly the listed Deployments.
- `test_docs.py` is updated for the deleted `DEPLOYER.md`. It checks that the README names every input, command, FAIL id and fault.

**Not possible offline:** a live run. The images are amd64-only, and there is no cluster here. The owner's first agent run is the end-to-end test. Its report settles the inferred items above, and the thresholds are tuned from its baseline.

## Refinements from the dry-run (2026-09-26)

The plan's code was written and tested in a scratch clone before the plan. That run refined these points of the design above:

1. **Runner tools.** The native `make reset-deploy` needs `helm` and `make`, so P1 checks `terraform kubectl helm make curl python3`.
2. **Step ids.** Applies are S1 (stage `datadog`), S2 (switch active faults off) and S3 (stage `lab`).
3. **S2, faults off before apply:**
   - Terraform owns the Deployments and `flagd-config` (server-side apply with `force_conflicts`), and `fault.sh` patches both. Re-applying over an active F3 would restore the memory limit but leave F3's JVM `command`.
   - So `up` finds the active faults (the flag config, F3's `command`, F15's `f15-nginx` volume) and runs `fault.sh off` for each, before stage `lab`.
4. **G4** is: no fault is on (the same detection as S2), and `fault.sh status` reports `false` for the six flag faults. That second check is flagd's own OFREP answer.
5. **P6** evaluates `local.unknown_services` with `terraform console`: the same YAML parse Terraform applies. A `terraform_data` precondition repeats the check at plan time.
6. **Host probe mount.** The probe mounts the node's `/etc` (type `Directory`, read-only) and tests `/host/etc/datadog-agent/datadog.yaml`. Mounting `/etc/datadog-agent` directly would make the kubelet create that directory on nodes where it is absent, which writes to the node OS (D2).
7. **G7** fails only when the Agent is this lab's. With another Agent it prints `WARN G7`, because this lab does not control that Agent's features.
8. **`deploy.yaml` in D1/D4.** D1 removes `deploy.yaml` only if D1 generated it, and asserts the removal. A `deploy.yaml` from an earlier `make deploy` is kept, so D4 has no `git status` check.
9. **Committed lock files.** `.terraform.lock.hcl` for both stages is committed, locked for `linux_amd64`, `linux_arm64`, `darwin_amd64` and `darwin_arm64`: helm 3.3.0, kubernetes 3.2.1, datadog 4.22.0. `lab/terraform/.gitignore` ignores `.terraform/` and state.
10. **Tests:**
    - `test_terraform_datadog.py` and `test_terraform_lab.py` (fmt, validate, evaluated locals, chart render);
    - `test_lab_sh.py` with `stub_cli.py`, one stub for `kubectl`/`terraform`/`curl`/`make`/`sleep`/`date`;
    - `test_docs.py`, which checks that the README covers every input, step id and monitor.

## Known limitations

1. The first live run is the first end-to-end run.
2. Tornado tracing under SSI is unproven, so the F22 pass signal is the driver's log monitor.
3. No generic monitor catches F1.
4. With a pre-existing Agent, APM, log and state-metric coverage is unverified, and the APM monitors may show No Data.
5. APM hosts are billed on the monthly high-water mark (lower 99% of hourly counts). More than about 7 h on N nodes bills N hosts for that month, even if APM is turned off afterwards.
6. Terraform state is local per workspace. If it is lost, the teardown is manual.
7. The runner needs cluster-admin: the Operator installs CRDs and cluster roles, and the host probe uses `hostPath`.

## Out of scope

- Notifications.
- Log facets and pipelines.
- Dashboards.
- The other seven faults' tests (`fault.sh` still toggles them).
- Remote Terraform state.

## Review amendments (fix round, 2026-09-26)

1. **H1:** `down`'s D3 also deletes `mutatingwebhookconfiguration datadog-webhook --ignore-not-found`, since neither Terraform nor the Helm chart removes it. The lost-state teardown gets the same step.
2. **M1:** the OOMKilled monitor queries `kubernetes.containers.last_state.terminated{reason:oomkilled}`, not `state.terminated`: an OOM-killed container restarts, so its current state is Waiting/CrashLoopBackOff, and the reason lives in `lastState`.
3. **L1:** `down`'s D1 no longer generates or removes `yamls/deploy.yaml`; it runs `make reset-deploy Namespace=train-ticket` directly, since the tracked `sw_deploy.yaml` already names the same 46 Deployments.
4. **H2:** every pod template carries `ad.datadoghq.com/tags: {"lab":"<LAB_NAME>"}`. The Kubernetes and log monitors and G7 scope on `lab:<LAB_NAME>`, not on the cluster name or namespace. So labs sharing a Datadog org stay apart, and the Kubernetes monitors also work with a foreign Agent.
5. **M7:** a new optional input, `KUBELET_TLS_VERIFY` (default `true`), sets the DatadogAgent's `global.kubelet.tlsVerify` when this lab installs the Agent. The README says which distributions need `false`.
6. **M6:** `test` switches off any fault left on, e.g. by a killed earlier run, before T1. The README states the worst-case run times.
7. **M9:** D3 destroys the agent release first, waits for its DatadogAgentInternal objects to be deleted, then destroys the Operator.
8. **Also fixed, with no design change:**
   - C1, M2–M5, L2, L3, L9, L10;
   - the tests M8 asked for;
   - two review findings: the ERR trap now reports only from the top-level shell (R1), and G5 samples the newest pod (R2).
9. **Deferred to the backlog by the owner:** L4–L8, L11 and L12.

## Live-run amendments (first run on a k3s box, 2026-09-26)

1. **MySQL and Nacos release timeouts are 1800 s:** a 3-replica MySQL took ~22 min, since its replicas start in order.
2. **All four Helm releases set `upgrade_install`:** a timed-out install isn't kept in state, and a plain retry collides with the leftover release.
3. **Stage `lab` adds a `root@'::1'` account on every MySQL pod after each MySQL release,** outside the binlog; Nacos and the Deployments wait for it. Where pods have an IPv6 loopback, xenon's `root@localhost` health check arrives from `::1`, is denied under `skip-name-resolve`, and no leader is elected. This matches upstream train-ticket #234, #233, #246 and #268, and it is RadonDB's own fix (radondb-mysql-kubernetes #441).
4. **Stage `lab` switches Nacos's 1.x double write off on every apply,** after the Nacos release and before the Deployments. Nacos 2.0.1 in cluster mode starts in 1.x compatibility and serves gRPC only once every member passes its upgrade check; on the box the check never passed, and every service's register was refused. 2.0.1 has no startup property for it, so the step calls Nacos's operator switch (`doubleWriteEnabled=false`) on each member and reads it back. The switch lives in memory, hence every apply.
5. **The four lab images that fail on Spring Boot 2.7's circular-reference check** (basic, inside-payment, order-other, payment) get `SPRING_MAIN_ALLOWCIRCULARREFERENCES=true` in `deploy.yaml.sample`, which is Spring's documented fallback. The fork builds them on Boot 2.7.18, and their upstream `SecurityConfig` forms a bean cycle.
6. **Decision 6's switches also cover the chart workloads** (`nacos`, `nacosdb`, `tsdb`, `rabbitmq`), through each chart's `podLabels`/`podAnnotations`. The vendored Nacos and RabbitMQ charts gain those two values, with empty defaults, so their default render is unchanged. Without this, SSI injected the chart pods and their logs were always collected.
7. **P2 also checks each node's inotify limits** (at least 512 instances and 524288 watches, kind's known-issue values) with the P5 probe pod. At Ubuntu's default of 128 instances, services crash-looped and Nacos died.
8. **The driver's trip queries send `startPlace`.** auto-query `9d5bc2d` sends `startingPlace`, which this version's `TripInfo` doesn't bind, so the driver never booked an order, never called `/getVoucher`, and F22 could not be detected. T1 now waits for the driver's `/getVoucher` calls before switching F22 on.
9. **Terraform apply and destroy run with `-no-color`,** so logs and agents read plain text.
10. **`down` deletes the validating `datadog-webhook` too,** and D4 checks both kinds: the first live `down` left the validating one behind (the H1 fix only covered the mutating one).
