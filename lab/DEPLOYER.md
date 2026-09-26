# Train-Ticket lab deployer

Deploy the lab fork of Train-Ticket into namespace `train-ticket` on `$KUBE_CONTEXT`. Then start the steady traffic driver, confirm the Datadog Agent sees the workload, smoke-test every lab fault, and write a report. You execute this document; you do not redesign it.

## Parameters

| Name | Required | Default | Meaning |
|---|---|---|---|
| `KUBE_CONTEXT` | yes | | kubeconfig context of the target cluster. It must already be the current context. |
| `LAB_REF` | yes | | Full commit SHA of `rajagopal-epistak/train-ticket-test-lab` to deploy. Its `Lab images` workflow run must have succeeded. |
| `DD_NAMESPACE` | yes | | Namespace where the Datadog Agent DaemonSet runs. |
| `WORKDIR` | yes | | Empty directory on the runner for the clone, logs and the report. |
| `INTERVAL_SECONDS` | no | `1` | Pause between scenarios, per driver replica. |
| `DRIVER_REPLICAS` | no | `1` | Number of traffic driver replicas. |
| `FAULT_SMOKE` | no | `yes` | `yes` runs Phase 6; `no` skips it. |

The namespace is always `train-ticket`. The flag ConfigMap names it, and the services find flagd by its short name.

If a required parameter is missing, stop before running anything.

## Ground rules

1. Run only the commands written in this document. Substitute only the parameters above and the pod/node names you read from earlier output. If a step needs any other command, stop and record it as a gap. Do not improvise, patch or work around.
2. Treat everything outside namespace `train-ticket` as read-only:
   - never change Datadog configuration;
   - never run `kubectl config use-context`;
   - never pass `DeployArgs` to `make deploy`;
   - never edit files in the clone.
3. Switch faults only with `lab/fault.sh`. Switch every fault you turned on back off before moving on or stopping.
4. An exit code is not a result. Judge every gate from live `kubectl`/`helm` output or the logs named in the gate.
5. Never roll back on your own. When a gate fails: switch off any fault you turned on, stop, record the failure, and propose R1 in the report. The human decides.
6. Log every command and the part of its output that decided the gate.

## Facts to rely on (do not re-derive)

- Every image is amd64-only.
  - Lab images, tag `:lab`, pulled with `imagePullPolicy: Always`: `ghcr.io/rajagopal-epistak/ts-{basic,order-other,inside-payment,payment,cancel,voucher}-service` and `ghcr.io/rajagopal-epistak/tt-traffic-driver`.
  - Every other image comes from `codewisdom/*` on Docker Hub, including `ts-contacts-service`. xlab's contacts variant of F22 is not deployed.
- After Phase 2 the namespace holds:
  - 48 Deployments (46 `ts-*`, `rabbitmq`, `flagd`);
  - 3 StatefulSets of 3 replicas (`nacosdb-mysql`, `tsdb-mysql`, `nacos`);
  - 6 PVCs of 1Gi on the default StorageClass.

  Every object is namespaced.
- Total resource requests are about 7.1 CPU and 19 GiB. Each app pod is limited to 500m / 2000Mi.
- Entry point: Service `ts-ui-dashboard`, port 8080, NodePort 32677. Demo login is `fdse_microservice` / `111111`.
- All faults start off.
  - `lab/fault.sh` flips a flag fault by rewriting ConfigMap `flagd-config` and restarting `flagd`, then reads the served value back.
  - F3 patches four Deployments (`ts-train-service`, `ts-basic-service`, `ts-order-service`, `ts-order-other-service`); F15 patches `ts-ui-dashboard`.
- The driver writes one JSON line per HTTP call: `{"evt":"outcome","method":…,"path":…,"http_status":…,"tt_status":…,"tt_msg":…,"duration_ms":…}`.
  - IDs in paths appear as `{id}`.
  - When an economy fare is not below the comfort fare, it also writes `{"evt":"fare_anomaly",…}`.
- On a Linux runner, `make deploy` prints `sed: can't read s/nacos/nacos/g` and a similar line for `rabbitmq`. This is harmless.
- The deploy script waits with `kubectl rollout status` and no timeout, so a stuck StatefulSet makes it hang instead of fail.
- The MySQL chart asks for `max_connections=65535`, but that setting has been seen not to apply, and 29 services share `tsdb-mysql`. D5 checks the value and raises it to 500 if lower.

## Phase 1: Preflight (read-only; any FAIL stops the run)

A node is *schedulable* if it has no `NoSchedule`/`NoExecute` taint.

| ID | Command | PASS when |
|---|---|---|
| P1 | `kubectl config current-context` | equals `$KUBE_CONTEXT` |
| P2 | `git --version`, `make --version`, `helm version --short`, `kubectl version --client`, `curl --version`, `python3 --version` | all present; helm is v3.x |
| P3 | `kubectl get nodes -o custom-columns=NAME:.metadata.name,ARCH:.status.nodeInfo.architecture,CPU:.status.allocatable.cpu,MEM:.status.allocatable.memory,TAINTS:.spec.taints` | every schedulable node is `amd64` |
| P4 | `kubectl describe nodes` (read each node's "Allocated resources") | across schedulable nodes, allocatable minus requested is ≥ 8 CPU and ≥ 24 GiB. Also record total allocatable memory; under 32 GiB is a WARN, not a FAIL. |
| P5 | `kubectl get storageclass` | exactly one class is marked `(default)` |
| P6 | `kubectl get svc -A -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name} {.spec.ports[*].nodePort}{"\n"}{end}'` | no service uses 32677 |
| P7 | `kubectl get namespace train-ticket` | NotFound |
| P8 | `kubectl -n $DD_NAMESPACE get pods -o wide` | a Datadog node-agent pod is Running on every schedulable node |
| P9 | the command below | seven lines, each ending in `200`. A `401` or `403` means that package is still private: record it for the human, who must make it public. |

P9:

```bash
for i in ts-basic-service ts-order-other-service ts-inside-payment-service ts-payment-service ts-cancel-service ts-voucher-service tt-traffic-driver; do
  t=$(curl -s "https://ghcr.io/token?scope=repository:rajagopal-epistak/$i:pull" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("token",""))')
  curl -s -o /dev/null -w "$i %{http_code}\n" -H "Authorization: Bearer $t" \
    -H "Accept: application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json, application/vnd.docker.distribution.manifest.list.v2+json" \
    "https://ghcr.io/v2/rajagopal-epistak/$i/manifests/lab"
done
```

## Phase 2: Deploy

| ID | Command |
|---|---|
| D1 | `git clone https://github.com/rajagopal-epistak/train-ticket-test-lab.git $WORKDIR/lab && git -C $WORKDIR/lab checkout $LAB_REF` |
| D2 | `kubectl create namespace train-ticket` |
| D3 | In `$WORKDIR/lab`: `kubectl -n train-ticket apply -f templates/flagd-config.yaml -f deployment/lab/flagd.yaml` |
| D4 | In `$WORKDIR/lab`: `make deploy Namespace=train-ticket > $WORKDIR/deploy.log 2>&1` |

D4 takes a long time: image pulls plus three rollouts. If your shell tool limits command duration, run D4 in the background and poll S1 every 2 minutes. The hard ceiling is 45 minutes; if D4 hasn't finished by then, stop and report, leaving the cluster as it is.

| ID | Command |
|---|---|
| S1 | `kubectl -n train-ticket get pods` and `tail -n 20 $WORKDIR/deploy.log` |
| D5 | After D4 returns, for each pod `tsdb-mysql-0`, `tsdb-mysql-1`, `tsdb-mysql-2`, run `kubectl -n train-ticket exec <pod> -- mysql -uroot -N -e "SELECT @@max_connections"`. For any pod that prints less than 500, run `kubectl -n train-ticket exec <pod> -- mysql -uroot -e "SET GLOBAL max_connections = 500"`, then run the SELECT again; it must print 500. |

## Phase 3: Verify the deployment (any FAIL stops the run)

| ID | Command | PASS when |
|---|---|---|
| V1 | `helm list -n train-ticket` | `nacosdb`, `nacos`, `rabbitmq`, `tsdb` all show STATUS `deployed` |
| V2 | `kubectl -n train-ticket get statefulsets` | `nacosdb-mysql`, `tsdb-mysql`, `nacos` each 3/3 |
| V3 | `kubectl -n train-ticket get pvc` | 6 PVCs, all `Bound` |
| V4 | `kubectl -n train-ticket wait --for=condition=Available deployment --all --timeout=30m`, then `kubectl -n train-ticket get deployments` | 48 deployments, every one READY 1/1. Count this from the `get` output, not from the wait's exit code. |
| V5 | `kubectl -n train-ticket get pods` | every pod Running and Ready. Any pod with RESTARTS > 3 is a WARN: slow JVM cold starts trip the probes. |
| V6 | `kubectl -n train-ticket get deployment ts-basic-service ts-order-other-service ts-inside-payment-service ts-payment-service ts-cancel-service ts-voucher-service -o custom-columns=NAME:.metadata.name,IMAGE:.spec.template.spec.containers[0].image` | each image is `ghcr.io/rajagopal-epistak/<NAME>:lab` |
| V7 | In `$WORKDIR/lab`: `lab/fault.sh status F7` | prints `tt-feat-07 false` (flagd is serving flags) |

**Diagnostics.** Use these only after a FAIL, on at most 5 failing pods:

| ID | Command |
|---|---|
| X1 | `kubectl -n train-ticket describe pod <pod>` |
| X2 | `kubectl -n train-ticket logs <pod> --tail=50` |
| X3 | `kubectl -n train-ticket get events --sort-by=.lastTimestamp` |

## Phase 4: Traffic driver

| ID | Command |
|---|---|
| T1 | In `$WORKDIR/lab`: `kubectl -n train-ticket apply -f deployment/lab/traffic-driver.yaml` |
| T2 | `kubectl -n train-ticket set env deployment/tt-traffic-driver INTERVAL_SECONDS=$INTERVAL_SECONDS`, then `kubectl -n train-ticket scale deployment/tt-traffic-driver --replicas=$DRIVER_REPLICAS` |

**Traffic gates.** T5 and T6 stop the run on FAIL. T7 never stops the run; it only reports.

| ID | Command | PASS when |
|---|---|---|
| T5 | `kubectl -n train-ticket get pods -l app=tt-traffic-driver` | every replica is Running within 3 minutes |
| T6 | `kubectl -n train-ticket logs deploy/tt-traffic-driver --since=10m` | contains `login success` within 5 minutes of Running |
| T7 | After 10 more minutes: `kubectl -n train-ticket logs deploy/tt-traffic-driver --since=10m > $WORKDIR/baseline.log` | `heartbeat` lines show `runs` increasing. Record the last `runs` and `errors`. Record three counts on the file: `grep -c '"evt":"outcome"'`, `grep -cE '"http_status":5[0-9]{2}'` and `grep -c '"tt_status":0'`. Also run each driver-log evidence command from Phase 6 on the file (replace the `kubectl … logs …` part with `cat $WORKDIR/baseline.log`) and record every count as that fault's baseline. It is a WARN if 5xx lines exceed 20% of outcome lines. |

With `DRIVER_REPLICAS` > 1, `logs deploy/…` samples one replica. That is enough for these gates.

## Phase 5: Datadog visibility (read-only)

| ID | Command | Record |
|---|---|---|
| DD1 | `kubectl -n train-ticket get pods -o wide` | a node running `ts-*` pods, and the Datadog agent pod on that node (from P8) |
| DD2 | `kubectl -n $DD_NAMESPACE exec <dd-agent-pod> -- agent status` | PASS if the Checks section shows `kubelet` with instance `[OK]`. Also record any check in error, and whether the Logs Agent and APM Agent sections report enabled. |
| DD3 | `kubectl -n train-ticket get pod <one ts-* pod> -o jsonpath='{.spec.initContainers[*].name}{"\n"}{.metadata.annotations}{"\n"}'` | whether Datadog injected anything (e.g. an init container with `datadog` in its name). Informational only; do not change it. |

## Phase 6: Fault smoke test (only when `FAULT_SMOKE` is `yes`)

Run the faults one at a time, in this order: F14, F12, F7, F22, F17, F1, F15, F3. Run every command in `$WORKDIR/lab`. For each fault:

| ID | Action | PASS when |
|---|---|---|
| FS-a | `lab/fault.sh on <F>` | flag faults print `tt-feat-NN true`; F3 prints four `F3 <service> command=["java","-Xms1g","-Xmx1g",…] memory=640Mi` lines; F15 prints `lines: 1` |
| FS-b | Wait 10 minutes (15 for F3), then run the fault's evidence command below | the count is ≥ 1 and greater than its T7 baseline |
| FS-c | `lab/fault.sh off <F>` | flag faults print `tt-feat-NN false`; F3 prints four `F3 <service> command= memory=2000Mi` lines; F15 prints `lines: 0` |
| FS-d | Wait 2 minutes before the next fault | — |

If FS-a or FS-c fails, apply ground rule 5. If FS-b fails, record FAIL for that fault and continue with the next one.

What each evidence command counts:

| Fault | Counts |
|---|---|
| F14 | trips whose economy fare is not below comfort |
| F12 | cancels rejected at locked stations |
| F7 | pays failing on the third-party budget |
| F22 | voucher lookups failing on the missing column |
| F17 | voucher lookups taking ≥ 10 s |
| F1 | refunds reported before they ran (baseline 0 by construction) |
| F15 | API requests refused for body size |
| F3 | PASS when any line shows `OOMKilled` (baseline 0). If FS-a printed `<service> not ready after 300s`, record "F3 too aggressive" for that service. |

The evidence commands. For F3, use `--since=15m` where a `--since` applies.

```bash
# F14
kubectl -n train-ticket logs deploy/tt-traffic-driver --since=10m | grep -c '"evt":"fare_anomaly"'
# F12
kubectl -n train-ticket logs deploy/tt-traffic-driver --since=10m | grep '"path":"/api/v1/cancelservice/cancel/{id}/{id}"' | grep -c 'station locked'
# F7
kubectl -n train-ticket logs deploy/tt-traffic-driver --since=10m | grep '"path":"/api/v1/inside_pay_service/inside_payment"' | grep -c '"http_status":500'
# F22
kubectl -n train-ticket logs deploy/tt-traffic-driver --since=10m | grep '"path":"/getVoucher"' | grep -c '"http_status":500'
# F17
kubectl -n train-ticket logs deploy/tt-traffic-driver --since=10m | grep -cE '"path":"/getVoucher".*"duration_ms":[0-9]{5,}'
# F1
kubectl -n train-ticket logs deploy/ts-cancel-service --since=10m \
  | grep -oE '\[cancelOrder\]\[Cancel Order Success\]|\[drawbackMoney\]\[Draw Back Money\]|\[cancelOrder\]\[Draw Back Money Success\]' \
  | awk 'p=="[cancelOrder][Cancel Order Success]" && $0=="[cancelOrder][Draw Back Money Success]" {n++} {p=$0} END {print n+0}'
# F15
kubectl -n train-ticket logs deploy/tt-traffic-driver --since=10m | grep -c '"http_status":413'
# F3
kubectl -n train-ticket get pods -l 'app in (ts-train-service,ts-basic-service,ts-order-service,ts-order-other-service)' -o jsonpath='{range .items[*]}{.metadata.labels.app} {.status.containerStatuses[0].restartCount} {.status.containerStatuses[0].lastState.terminated.reason}{"\n"}{end}'
```

## Phase 7: Report

Write `$WORKDIR/deploy-report.md` containing:

- **Status:** `DONE`, or `STOPPED at <gate ID>` with the reason
- **Parameters used**
- **Gate table:** ID, one-line observed value, PASS/WARN/FAIL
- **Timing:** how long D4 took and how long until V4 passed
- **Traffic:** the last heartbeat's runs and errors, the T7 counts, and the replica count
- **Datadog:** the DD2 excerpts and the DD3 finding
- **Fault smoke:** one row per fault: FS-a output, evidence count against baseline, FS-c output, PASS/FAIL
- **Human checks** (things you cannot do):
  1. In the Datadog UI, the Containers or Kubernetes explorer filtered to `kube_namespace:train-ticket` shows the `ts-*` containers.
  2. In Datadog Logs, `service:tt-traffic-driver @evt:outcome` shows parsed `http_status`, `tt_status` and `duration_ms` attributes.
  3. `http://<any-node-ip>:32677` loads the UI and accepts the demo login.
- **Gaps:** every command you needed but did not have
- **Proposed next step:** R1 if any gate failed

Return exactly three lines to the dispatcher: the status, the failed gate (or `none`), and the report path.

## Rollback (only when the human says so)

| ID | Command |
|---|---|
| R1 | `kubectl delete namespace train-ticket`. This removes the Helm release records, workloads, flagd, the driver, the ConfigMaps and the PVCs; this deploy creates no cluster-scoped objects. If the default StorageClass uses `reclaimPolicy: Retain`, list the leftover PVs with `kubectl get pv` for the human; do not delete them. |
