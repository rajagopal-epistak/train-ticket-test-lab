# Lab handoff

Where the Train-Ticket Datadog fault lab stands on 2026-09-28: what works, what was decided, what is open, and what bit us. Read with:

- `lab/README.md`: the complete run guide (inputs, gates, troubleshooting).
- `docs/superpowers/specs/2026-09-26-lab-deploy-design.md`: the design. Its "Review amendments" and "Live-run amendments" sections override earlier text.
- `lab/live-run-findings.md`: every live-run problem (26) with root cause and fix.

## Status

- **Phase 1** (eight switchable faults, traffic driver, lab images) is on master: PR #1, merge commit `a4c1abce`.
- **Phase 2** (`lab/deploy`: Terraform in two stages, `lab/lab.sh up|test|down`, 12 Datadog monitors) is 37 commits on branch `lab/deploy`, pushed at `4e187f1c`, 150 tests passing. There is no PR yet.
- **Validated on 2026-09-27** on a single-node k3s sandbox (32 vCPU, 31 GiB), starting from an empty cluster. `up` passed in about 35 min, then `test` passed:

| Step | Result |
|---|---|
| T1 baseline | the driver calls `/getVoucher`; the Edge 5xx monitor is OK |
| T2 | F22 on; flagd serves it on |
| T3 | Edge 5xx `/getVoucher` group Alert after **65 s**; the APM "Voucher error rate" monitor Alert after 64 s |
| T4 | back to OK **526 s** after F22 off |

- **Proven live: F22 only.** F1, F3, F7, F12, F14, F15 and F17 are built and unit-tested but have not run on a cluster.
- **At handoff the validated lab (`LAB_NAME=tt-lab-1`) was still up on the sandbox**, so the Datadog Agent and APM were still accruing usage. `lab/lab.sh down` removes everything.

## Where things are

- Branch `lab/deploy`; worktree `~/Documents/barath/work/train-ticket-test-lab-deploy` (the main checkout stays on master).
- Images: `ghcr.io/rajagopal-epistak/<svc>:lab` and `:sha-<commit>`, built by `.github/workflows/lab-images.yaml` on pushes to master and `lab/**` that touch the seven image paths. The packages are public.
- Tools only via `mise exec terraform@1.16.4 helm@3.22.0 shellcheck@0.11.0 -- …`. The test command is in the README's "Build and test".
- Inputs of the validation run: `KUBE_CONTEXT=default LAB_NAME=tt-lab-1 DD_SITE=datadoghq.com APM_HOSTS_BUDGET=1 APM_INGEST_GB_BUDGET=150 KUBELET_TLS_VERIFY=true`, with `DD_API_KEY`/`DD_APP_KEY` exported in the environment only.
- Telemetry of the validation run: Appendix A. It keeps Datadog usage minimal (logs for the driver and voucher only, APM for voucher and basic only).

## Decisions (the owner's; details in the spec)

1. **Shape:** Terraform in two stages plus a thin `lab/lab.sh`, and the existing `lab/fault.sh`. The Datadog Agent comes from the Datadog Operator; the install is skipped when an Agent already runs in the cluster or on a node. Everything runs as Kubernetes workloads.
2. **APM:** on, through Single Step Instrumentation scoped to `train-ticket`. `APM_ENABLED=false` turns off SSI and the APM monitors. Budget monitors watch estimated usage.
3. **Monitors:** 12, fault-agnostic, with no notification handle by design; `test` reads their state through the API. F1 is an accepted gap. On 2026-09-27 the owner declined adding a notification input for now.
4. **Test fault:** F22, passing on the driver's Edge 5xx log monitor. The APM error monitor is reported only (it did alert).
5. **Teardown:** `down` runs the repo's own `make reset-deploy` first, then `terraform destroy` for both stages, then deletes both `datadog-webhook` kinds.
6. **Telemetry switches:** `lab/telemetry.yaml` `logs_off`/`apm_off` take Deployment names and the chart release names (`nacos`, `nacosdb`, `rabbitmq`, `tsdb`).
7. **Logs:** the whole namespace; no log budget monitor.
8. **Docs:** `lab/README.md` is the complete run guide (`DEPLOYER.md` is retired).
9. **Minimal changes:** with every flag off, behaviour equals upstream/xlab. Vendored chart edits render identically by default.
10. **Deploy level:** `""` only. Never `--independent-db` unless the owner says so.
11. **MySQL first-time init (2026-09-27):** a startup probe (chart value, 10 s × 60, running the liveness command) plus a guard that fails `up` on a half-initialised pod. Rejected: raising the liveness `initialDelaySeconds`, which would blind liveness for 10 min after every later restart.
12. Review 3's nits F4 and F5 stay as they are.

## Open items, in rough order

1. **Keep `tt-lab-1` up to explore faults, or `down` it.** Datadog bills hosts on the high-water mark of the lower 99% of hourly counts, so more than about 7 h in a month makes the host count for the month (APM host list price $31).
2. **Tune two noisy monitors.** Both alert with no fault on:
   - "Business rejections by path" (threshold 20): the driver's normal rejections exceed it.
   - "Voucher p95 latency" (2 s): `/getVoucher` p95 was about 1.9 s with spikes to 6.7 s on a box at 26 of 31 GiB.
   F12 and F17 rely on these two, so their alerts can't be told from noise until the thresholds move.
3. **Run the other seven faults live** (`lab/fault.sh on|off F<n>`), each confirming its intended monitor: F3 → OOMKilled/Restarts, F7 → Java latency/error rate, F12 → Business rejections, F14 → Fare anomaly, F15 → Edge 4xx, F17 → Voucher p95 latency. F3 is a memory fault and the lab already uses about 23.5 GiB.
4. **Nacos has no liveness probe (finding #22).** The chart ignores its own `health.enabled`, and the image keeps the container Running after the JVM dies. A probe restart would lose the in-memory double-write switch until `up` re-runs, so this needs a decision. nacos-k8s uses a startup probe (180 s) plus HTTP liveness/readiness, but on 3.x paths; the 2.0.1 endpoint is unverified.
5. **Open a PR `lab/deploy` → master.** Merging needs the owner's explicit yes.
6. **Review backlog** (deferral approved by the owner):
   - L4: the README P3 row puts the key in argv (`curl -H "DD-API-KEY: …"`); use `-K -` as `dd_call` does.
   - L5: README troubleshooting commands lack `--context "$KUBE_CONTEXT"`, and T0's `terraform output` has no workspace.
   - L6: the README Costs text claims a later `up` restarts pods; it does only in G5's fallback.
   - L7: the prerequisites miss the logs-read and timeseries-query permissions G7 needs; `mise use` without `-g` writes a `mise.toml` into the repo.
   - L8: a non-numeric `APM_*_BUDGET` passes P0 and then fails P6 with the wrong message.
   - L11: spec/code drift (G7.1 uses a metric query, not `/api/v1/hosts`; a G2 FAIL doesn't show events; the report prints durations, not timestamps). Decide which side moves.
   - L12: the fixed log path `/tmp/lab-native-reset.log`; `tt-lab-probe` leaks if P5 is interrupted; a cluster with the Operator but no DatadogAgent passes P5, then S1 hits a CRD ownership conflict.
7. **Deferred by the owner:** a `lab/lab.sh telemetry` on-the-fly toggle with an allow-list (deferred until validation passed, which it now has); a `DEPLOY_ARGS` input.
8. **Phase-1 leftovers:** `lab/README.md` on master still says new packages start private; F12's `isLockedStation` has no null guard; F7/F1 use the shared commonPool; `fault.sh`'s cluster functions are untested.
9. **Backlog:** phase-3 faults F6, F10, F16, F20 (Hagenberg as the spec); Chaos Mesh; a DB access-control fault class; muBench for topology tests.
10. **Parked spike:** Kubernetes-native routing instead of Nacos (below). Unpark only on the owner's say-so.

## What bit us (read before changing the deploy)

Finding numbers refer to `lab/live-run-findings.md`.

- **MySQL first-time init** takes about 2 min when six pods initialise at once, and the chart's liveness probe allows 60 s. A kill mid-init leaves `$DATADIR/mysql`, so the restart skips init: no app user, no database, and xenon may elect that pod leader (#20; docker-library/mysql #439 is the same mechanism). Readiness (root's `SELECT 1` over the socket) also passes on the entrypoint's temporary server, which runs with networking off, so Helm's wait does not mean init is done (#24). A liveness restart just after init is harmless (#23).
- **xenon** health-checks `root@localhost`, which arrives from `::1`, so every pod needs `root@'::1'` (#3). On a re-run, followers are `super_read_only` (#10).
- **Never run `xenoncli mysql rebuildme` here.** It needs SSH between pods, which this chart doesn't configure; it killed mysqld and left nacosdb leaderless for 75 s (#21). Re-initialise a bad replica by deleting its PVC and pod.
- **Nacos 2.0.1** in cluster mode stays in 1.x double-write mode and refuses gRPC registrations. The operator switch lives in memory, so `up` sets it on every apply (#12). Nacos 2.1.0 turns it off by default; 2.2.0 removes it.
- **Node inotify limits** must be at least 512 instances and 524288 watches (#8).
- **Spring Boot 2.7** (the fork's parent pom) rejects the SecurityConfig cycle in four rebuilt images; `SPRING_MAIN_ALLOWCIRCULARREFERENCES=true` is the documented fallback (#13).
- **ts-avatar** needs AVX (dlib) and crash-loops on a QEMU CPU model without it (#14).
- **The driver:** auto-query sent `startingPlace`, which this `TripInfo` doesn't bind (#15). Cold JVMs make the first bookings outlast nginx's 60 s (#17).
- **Shell:** `kubectl run -i --rm` loses the output of a fast container (#19). `grep -q` in a `pipefail` pipeline fails when the producer is still writing after the match (#25).
- **Memory:** the lab uses about 23.5 of 31 GiB (the three Nacos pods about 5.2 GiB), enough to trip an org-wide host memory monitor (#26).
- **Something outside the lab** deleted namespaces on the box once (#6).
- **Never trust an exit code** for infrastructure; query the live state.

## Research

### Nacos 2.x + MySQL on Kubernetes (2026-09-27)

- Kubernetes docs ("Protect slow starting containers with startup probes"): "The solution is to set up a startup probe with the same command, HTTP or TCP check, with a `failureThreshold * periodSeconds` long enough to cover the worst case startup time."
- docker-library/mysql #439 (closed) is our mechanism. Maintainer: "I think the real solution is to increase your health timeout on first start". A marker file was rejected because `mysqld --initialize-insecure` needs an empty directory.
- The Bitnami MySQL chart has a startup probe on by default. The RadonDB operator has none (liveness `initialDelaySeconds: 30`).
- `nacos-group/nacos-k8s`: a single MySQL instance; Nacos gets a startup probe (180 s) plus HTTP liveness/readiness.
- FudanSELab/train-ticket #233, #234, #293: the same leader/read-only symptom, fixed by hand. #246, #252, #268: storage or Kubernetes version problems.
- Nacos release notes: 2.1.0 closes the 1.x upgrade support by default; 2.2.0 removes the double-write code.
- Not found anywhere: the kill → half-init → leader chain, or xenon's election criteria.

### Parked spike: Kubernetes-native routing instead of Nacos (2026-09-27)

Nacos is the most fragile link: nacosdb → Nacos 2.0.1 (3 replicas) → about 41 Spring services that fail to start if they can't register.

- **Wiring:** the fork's parent pom (Boot 2.7.18, Spring Cloud 2021.0.8) uses `spring-cloud-starter-alibaba-nacos-discovery` (discovery only) and `spring-cloud-starter-loadbalancer`. The upstream prebuilt images use Ribbon. Services call a `@LoadBalanced` RestTemplate at `http://<service>` with no port, so a registry lookup is mandatory. The gateway's 40 routes are `lb://…`. The dashboard nginx, voucher and flagd already use Kubernetes DNS.
- **Rejected: Eureka.** It means swapping the client in the parent pom and rebuilding about 41 images (35+ prebuilt upstream), and there is no official server image.
- **Spike design, config only, no rebuilds:** one `SPRING_APPLICATION_JSON` per Java Deployment and the gateway, setting `spring.cloud.nacos.discovery.enabled=false`; `spring.cloud.discovery.client.simple.instances.<svc>[0].uri=http://<svc>:<port>` for the LoadBalancer images; and `<svc>.ribbon.listOfServers=<svc>:<port>` for the Ribbon images. It drops six pods and the slowest part of `up`. A single JSON variable is needed because environment relaxed binding can't express hyphenated map keys.
- **Fault impact:** no fault's mechanism changes, only name resolution (F15 already uses DNS; F17 and F22 never registered). F3's Edge 5xx blip may get shorter, because an endpoint drops out on NotReady. Load balancing moves from per request to per connection, which is irrelevant at one replica. The lab loses registry faults as a surface; none is in the catalogue.
- **It changes the "behaviour equals upstream" rule**, so it needs the owner's ratification first.
- **To verify in the spike:** which stack the gateway uses; that the Hoxton-era images honour `enabled=false` and fall back to Ribbon's `listOfServers`; that the simple client wins over a disabled Nacos client.
- **Spike plan:** build the name → port map from `svc.yaml`; apply to the booking chain first (gateway, preserve → basic/seat/order/travel/contacts); roll out and remove the nacos and nacosdb releases; switch each fault on and off to confirm its signal.

## Appendix A: telemetry of the validation run

Copy over `lab/telemetry.yaml` for a low-cost run: logs only for `tt-traffic-driver` and `ts-voucher-service`, APM only for `ts-voucher-service` and `ts-basic-service` (G5 checks basic), and the chart releases off.

<details><summary>lab/telemetry.yaml</summary>

```yaml
logs_off: [flagd, ts-admin-basic-info-service, ts-admin-order-service, ts-admin-route-service, ts-admin-travel-service, ts-admin-user-service, ts-assurance-service, ts-auth-service, ts-avatar-service, ts-basic-service, ts-cancel-service, ts-config-service, ts-consign-price-service, ts-consign-service, ts-contacts-service, ts-delivery-service, ts-execute-service, ts-food-delivery-service, ts-food-service, ts-gateway-service, ts-inside-payment-service, ts-news-service, ts-notification-service, ts-order-other-service, ts-order-service, ts-payment-service, ts-preserve-other-service, ts-preserve-service, ts-price-service, ts-rebook-service, ts-route-plan-service, ts-route-service, ts-seat-service, ts-security-service, ts-station-food-service, ts-station-service, ts-ticket-office-service, ts-train-food-service, ts-train-service, ts-travel-plan-service, ts-travel-service, ts-travel2-service, ts-ui-dashboard, ts-user-service, ts-verification-code-service, ts-wait-order-service, nacos, nacosdb, rabbitmq, tsdb]
apm_off: [flagd, ts-admin-basic-info-service, ts-admin-order-service, ts-admin-route-service, ts-admin-travel-service, ts-admin-user-service, ts-assurance-service, ts-auth-service, ts-avatar-service, ts-cancel-service, ts-config-service, ts-consign-price-service, ts-consign-service, ts-contacts-service, ts-delivery-service, ts-execute-service, ts-food-delivery-service, ts-food-service, ts-gateway-service, ts-inside-payment-service, ts-news-service, ts-notification-service, ts-order-other-service, ts-order-service, ts-payment-service, ts-preserve-other-service, ts-preserve-service, ts-price-service, ts-rebook-service, ts-route-plan-service, ts-route-service, ts-seat-service, ts-security-service, ts-station-food-service, ts-station-service, ts-ticket-office-service, ts-train-food-service, ts-train-service, ts-travel-plan-service, ts-travel-service, ts-travel2-service, ts-ui-dashboard, ts-user-service, ts-verification-code-service, ts-wait-order-service, tt-traffic-driver, nacos, nacosdb, rabbitmq, tsdb]
```

</details>
