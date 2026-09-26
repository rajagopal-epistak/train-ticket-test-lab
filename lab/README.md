# Train-Ticket fault lab

This fork is xlab-uiuc/train-ticket (FudanSELab/train-ticket plus flagd-guarded faults), with eight wiki faults made switchable and a steady traffic driver, monitored with Datadog.

One command stands the lab up on any x86_64 Kubernetes cluster:
- the Datadog Agent, unless one is already there;
- Train-Ticket;
- flagd and the traffic driver;
- a set of fault-agnostic Datadog monitors.

A second command proves a monitor catches an injected fault. A third removes everything. All faults start off.

## Faults

| Fault | Switch | What changes when on | Evidence | Monitor that should notice |
|---|---|---|---|---|
| F1 | `tt-feat-01` | ts-cancel-service reports the refund before running it; the refund lands 8 s later | cancel-service log order | none (known gap) |
| F3 | `lab/fault.sh on F3` | train, basic, order and order-other services run a 1g heap inside a 640Mi limit | OOMKilled restarts | OOMKilled by deployment, Restarts by deployment |
| F7 | `tt-feat-07` | inside-payment pays through ts-payment-service with a 2 s budget; payment answers in 1.5–2.5 s | HTTP 500 on `inside_payment` | Java p95 latency by service, Java error rate by service, Edge 5xx by path |
| F12 | `tt-feat-12` | ts-order-other-service rejects cancels of K/Z/T-series orders touching Shanghai or Nanjing | `tt_status` 0, "station locked" | Business rejections by path |
| F14 | `tt-feat-14` | ts-basic-service prices economy seats at distance × 1 | `fare_anomaly` lines | Fare anomaly |
| F15 | `lab/fault.sh on F15` | the dashboard's nginx refuses API bodies over 300 bytes (bookings with food or consign) | HTTP 413 | Edge 4xx by path |
| F17 | `tt-feat-17` | ts-voucher-service sleeps 10 s in MySQL per lookup (from xlab) | `/getVoucher` ≥ 10 s | Voucher p95 latency |
| F22 | `tt-feat-22` | ts-voucher-service's lookup names a missing column, so Print Voucher shows "Empty. No data!" | HTTP 500 on `/getVoucher` | Edge 5xx by path (the `test` pass signal), Voucher error rate |

Switch any fault with `lab/fault.sh on|off|status <F>`. It uses kubectl's current context and namespace `train-ticket` (override with `NAMESPACE`). `lab/lab.sh` pins the context for you.

## Prerequisites

**On the machine that runs the script:**
- `terraform` 1.8 or later (1.16.x tested);
- `kubectl`, `helm` (for the repo's native `make reset-deploy`), `make`, `curl`, `python3`, `git`.

With mise: `mise use terraform@1.16 helm@3 kubectl@1`.

**The cluster:**
- x86_64 nodes only; the images are amd64;
- a default StorageClass;
- about 8 CPU and 32 GiB free;
- a kubeconfig context with cluster-admin. The Datadog Operator installs CRDs and cluster roles, and the host check uses `hostPath`.

**Datadog:**
- an API key;
- an application key allowed to read and write monitors;
- your site (e.g. `datadoghq.eu`).

**Images:** `ghcr.io/rajagopal-epistak/*:lab` must be public. They are already built by `.github/workflows/lab-images.yaml`.

## Inputs

Every input is an environment variable. Keys are never written to a file, a command line or Terraform state.

| Variable | Required | Example | Meaning |
|---|---|---|---|
| `KUBE_CONTEXT` | yes | `lab-ctx` | the only kubeconfig context the script touches |
| `LAB_NAME` | yes | `tt-lab-1` | lowercase DNS label; the Datadog cluster name, the `env` tag, the `lab:` tag, the monitor-name prefix and the Terraform workspace |
| `DD_SITE` | yes | `datadoghq.eu` | Datadog site |
| `DD_API_KEY` | yes | | Datadog API key |
| `DD_APP_KEY` | yes | | Datadog application key |
| `APM_HOSTS_BUDGET` | yes | `4` | the APM hosts budget monitor alerts above this |
| `APM_INGEST_GB_BUDGET` | yes | `150` | monthly ingested-span budget in GB; the monitor alerts when a day exceeds budget ÷ 30 |
| `APM_ENABLED` | no (`true`) | `false` | `false` turns off APM injection and the APM monitors |

## Run

```bash
export KUBE_CONTEXT=lab-ctx LAB_NAME=tt-lab-1 DD_SITE=datadoghq.eu
export DD_API_KEY=... DD_APP_KEY=...
export APM_HOSTS_BUDGET=4 APM_INGEST_GB_BUDGET=150
lab/lab.sh up      # 20-40 min on a fresh cluster; safe to run again
lab/lab.sh test    # 10-40 min: F22 on, wait for the alert, F22 off, wait for recovery
lab/lab.sh down    # removes everything this lab created
```

Each step prints `PASS <id>` or `FAIL <id>: <reason>`, and the first FAIL stops the command with exit 1. A good `up` ends with `UP PASS lab=tt-lab-1 agent=installed apm=true`, `test` with `TEST PASS lab=tt-lab-1`, and `down` with `DOWN PASS lab=tt-lab-1`.

### `up`

| Id | Checks or does |
|---|---|
| P0 | the inputs are present and well-formed |
| P1 | the tools are on `PATH`; Terraform is 1.8 or later |
| P2 | the context exists; every node is Ready and amd64; there is a default StorageClass |
| P3 | the API key is valid and the application key can read monitors |
| P4 | namespace `train-ticket` is absent, or labelled `lab=<LAB_NAME>` |
| P6 | `lab/telemetry.yaml` names only known deployments |
| P5 | Agent decision: keep this lab's Agent. Skip the install if any other Agent runs in the cluster, or is installed on a node's OS (`/etc/datadog-agent/datadog.yaml`). Otherwise install it. |
| S1 | Terraform stage `datadog`: the Datadog Operator (chart 2.27.0) and a DatadogAgent (Agent 7.83.3) with logs, Kubernetes state metrics and APM Single Step Instrumentation for `train-ticket` |
| G1 | the Cluster Agent and every node Agent are ready; admission webhook `datadog-webhook` exists |
| S2 | any fault that is on is switched off, so the apply restores the baseline |
| S3 | Terraform stage `lab`: namespace, MySQL × 2, Nacos, RabbitMQ, 46 services, flagd, traffic driver, monitors |
| G2 | every deployment and statefulset in `train-ticket` is ready (20 min budget) |
| G3 | tsdb MySQL `max_connections` is at least 500 (set on every run; MySQL forgets it on restart) |
| G4 | all eight faults are off, and flagd serves every flag as off |
| G5 | `ts-basic-service` pods carry the Datadog APM init container |
| G6 | the traffic driver logs outcome lines (`"evt":"outcome"`) |
| G7 | Datadog receives Kubernetes metrics, the driver's logs and APM traces. When the Agent isn't this lab's, this is a WARN rather than a FAIL. |

### `test`

| Id | Checks or does |
|---|---|
| T0 | the monitors exist, and `tt-traffic-driver` is not in `logs_off` |
| T1 | baseline: the Edge 5xx monitor's `/getVoucher` group is not alerting (waits up to 20 min) |
| T2 | `lab/fault.sh on F22`, and flagd serves it on |
| T3 | the Edge 5xx monitor's `/getVoucher` group reaches Alert within 15 min |
| T4 | `lab/fault.sh off F22`, and the group is back to OK within 15 min |

The report lines give detection and recovery times, whether the APM Voucher error rate monitor also fired, every monitor's state before and after, and the uncovered fault (F1). F22 is switched off even when the test fails.

### `down`

| Id | Checks or does |
|---|---|
| D1 | the repo's native teardown: generates `deploy.yaml` the way `make deploy` does, runs `make reset-deploy Namespace=train-ticket`, then removes the generated file. A `deploy.yaml` you created is kept. |
| D2 | Terraform destroys stage `lab`: what the native reset misses (the `tsdb` release, flagd, the driver), the monitors, and namespace `train-ticket` with its volumes |
| D3 | Terraform destroys stage `datadog`, only if this lab installed the Agent. Any other Agent is left alone. |
| D4 | the namespaces and webhook are gone, and no monitor tagged `lab:<LAB_NAME>` remains |

## Monitors

All monitors are named `[<LAB_NAME>] …` and tagged `lab:<LAB_NAME>` and `managed-by:terraform`. None has a notification handle; `test` reads their state through the API. The thresholds are starting values, to be tuned from the first baseline.

| Monitor | Watches |
|---|---|
| Java p95 latency by service | APM `trace.servlet.request` p95 > 2 s, per service |
| Voucher p95 latency | APM `trace.tornado.request` p95 > 2 s |
| Java error rate by service | APM servlet errors ÷ hits > 10 %, per service |
| Voucher error rate | APM Tornado errors ÷ hits > 10 % |
| OOMKilled by deployment | a container terminated with `oomkilled` |
| Restarts by deployment | more than 2 restarts in 10 min |
| Edge 5xx by path | driver outcomes with HTTP 500/502/503/504, more than 2 per path in 10 min |
| Edge 4xx by path | driver outcomes with HTTP 400/401/403/404/413, more than 5 per path in 10 min |
| Business rejections by path | driver outcomes with `tt_status` 0, more than 20 per path in 10 min |
| Fare anomaly | any driver `fare_anomaly` line |
| APM hosts budget | `datadog.estimated_usage.apm_hosts` above `APM_HOSTS_BUDGET` |
| APM ingestion budget (daily share) | `datadog.estimated_usage.apm.ingested_bytes` in a day above `APM_INGEST_GB_BUDGET` ÷ 30 |

## Per-service switches

`lab/telemetry.yaml` switches log collection or APM off for single services:

```yaml
logs_off: [ts-news-service]    # adds pod annotation ad.datadoghq.com/logs_exclude: "true"
apm_off: [tt-traffic-driver]   # adds pod label admission.datadoghq.com/enabled: "false"
```

Names are deployment names: the 46 `ts-*` services, `tt-traffic-driver`, and `flagd`. Run `lab/lab.sh up` again to apply; Kubernetes rolls the listed deployments. The switches live on the pods, so they also work with an Agent this lab did not install. Leave `tt-traffic-driver` out of `logs_off`: every log monitor and the `test` pass signal read its logs.

## Costs

- **APM hosts** are billed on the month's high-water mark: the maximum of the lower 99 % of hourly host counts. So more than about 7 hours of APM on N nodes in a month bills N APM hosts for that month, even if you turn APM off afterwards.
- **Spans and logs** are billed by volume, and that charge stops as soon as you turn them off.
- **The budget monitors** watch Datadog's estimated usage.
- **Turning APM off:** re-run `up` with `APM_ENABLED=false`. That stops injection into newly created pods. Pods that are already running keep the tracer until they restart. A later `up`, or `kubectl -n train-ticket rollout restart deployment`, restarts them.

## Troubleshooting

| FAIL | Likely cause | Look with |
|---|---|---|
| P0 | an input is missing, or `LAB_NAME` isn't a lowercase DNS label | `env \| grep -E 'KUBE_CONTEXT\|LAB_NAME\|DD_\|APM_'` |
| P1 | a tool is missing, or Terraform is older than 1.8 | `terraform version` |
| P2 | wrong context, a NotReady or arm64 node, or no default StorageClass | `kubectl --context $KUBE_CONTEXT get nodes -L kubernetes.io/arch; kubectl get storageclass` |
| P3 | wrong key or wrong site | `curl -s -H "DD-API-KEY: $DD_API_KEY" https://api.$DD_SITE/api/v1/validate` |
| P4 | `train-ticket` belongs to another lab, or to a manual `make deploy` | `kubectl get namespace train-ticket --show-labels` |
| P5 | namespace `datadog` exists and is not this lab's | `kubectl get namespace datadog --show-labels` |
| P6 | a typo in `lab/telemetry.yaml` | the FAIL line lists the unknown names |
| S1 | Operator chart or DatadogAgent apply failed | `kubectl -n datadog get pods; kubectl -n datadog describe datadogagent datadog` |
| G1 | Agent pods not ready; often the image pull or the node's Pod Security | `kubectl -n datadog get pods -o wide; kubectl -n datadog logs deploy/datadog-cluster-agent` |
| S2 | `lab/fault.sh off` failed | run `lab/fault.sh status <F>` for the named fault |
| S3 | Terraform apply of the lab failed; the error names the resource | re-run `up` (it is idempotent) |
| G2 | a service can't start (often MySQL or Nacos still starting, or the quota) | `kubectl -n train-ticket get pods \| grep -v Running; kubectl -n train-ticket describe pod <pod>` |
| G3 | MySQL not answering | `kubectl -n train-ticket exec tsdb-mysql-0 -- mysql -uroot -e 'SELECT 1'` |
| G4 | a fault is still on, or flagd isn't serving | `lab/fault.sh status F22; kubectl -n train-ticket logs deploy/flagd` |
| G5 | pods created before the webhook; `up` restarts them once | `kubectl -n train-ticket get pod -l app=ts-basic-service -o jsonpath='{.items[0].spec.initContainers[*].name}'` |
| G6 | the driver can't reach the dashboard, or its image didn't pull | `kubectl -n train-ticket logs deploy/tt-traffic-driver --tail=20` |
| G7 | Datadog isn't receiving data; check the Agent status | `kubectl -n datadog exec ds/datadog-agent -- agent status` |
| T0 | `up` hasn't run for this `LAB_NAME`, or the driver's logs are switched off | `terraform -chdir=lab/terraform/lab output monitor_ids` |
| T1 | `/getVoucher` is already failing | `kubectl -n train-ticket logs deploy/ts-voucher-service --tail=50` |
| T2, T4 | flagd didn't pick up the flag | `lab/fault.sh status F22` |
| T3 | no alert: check the driver's `/getVoucher` outcomes in Datadog Logs (`service:tt-traffic-driver @path:/getVoucher`) | the Edge 5xx monitor page in Datadog |
| D1 | the native reset reported errors; its log path is printed, and errors for missing objects are expected | the log file named in the D1 line |
| D2, D3 | Terraform destroy failed | re-run `down` |
| D4 | something survived | `kubectl get namespace train-ticket datadog`, and monitors tagged `lab:<LAB_NAME>` in Datadog |

**If the Terraform state is lost** (`lab/terraform/*/terraform.tfstate.d/<LAB_NAME>`), tear down by hand:
1. `make reset-deploy Namespace=train-ticket`;
2. `kubectl delete namespace train-ticket`;
3. if this lab installed the Agent: `kubectl delete datadogagent -n datadog datadog`, `helm -n datadog uninstall datadog-operator`, `kubectl delete mutatingwebhookconfiguration datadog-webhook --ignore-not-found`, `kubectl delete namespace datadog`;
4. delete the monitors tagged `lab:<LAB_NAME>` in Datadog.

## Build and test

- **Images:** `.github/workflows/lab-images.yaml` builds the six changed services and the driver to `ghcr.io/rajagopal-epistak/*:lab` on push.
- **Java:** `hack/lab/mvn.sh <module> test`.
- **Python, shell and Terraform:** `mise exec terraform@1.16.4 helm@3 -- uv run --no-project --with pytest==8.3.3 --with pyyaml==6.0.2 --with requests==2.32.3 --with tornado==6.5.10 --with pymysql==1.2.3 pytest lab traffic-driver ts-voucher-service/tests -q`.
- **auto-query:** `traffic-driver/autoquery/` is an unmodified copy of FudanSELab/train-ticket-auto-query at `9d5bc2d`.
