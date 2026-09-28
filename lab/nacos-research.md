# Nacos: restart safety and upgrade options

Research of 2026-09-28 for handoff open item 4 (finding #22: nothing restarts a failed Nacos). The owner's decision: stay on Nacos 2.0.1, add the chart's probes and a postStart hook that turns double write off (option 2 below). The upgrade to 2.5.x or 3.x was assessed and dropped, because it fixes only #12 of the Nacos problems we hit. Everything below was checked against the source at the named tag or the named document, unless it is marked inferred or unmeasured. Live-run observations come from the support session's transcript (session c3942e75). The review of 2026-09-28 found the deadlock described under option 2 and reproduced some facts locally with podman.

## How the 2.0.1 double-write switch works

- **The gRPC gate is per member.** `GrpcRequestFilter` rejects every naming request while `upgradeJudgement.isUseGrpcFeatures()` is false, with the #12 message ("Nacos cluster is running with 1.X mode, can't accept gRPC request temporarily...").
- **Two paths set `useGrpcFeatures`:**
  - `UpgradeJudgement` checks every 5 s. A member is ready when its v1 and v2 service/instance counts match and its double-write queue is empty; the upgrade needs every member ready. On the live run it never passed.
  - `DoubleWriteEventListener.DoubleWriteEnabledChecker` reads the member's own `SwitchDomain` every 5 s. Once `doubleWriteEnabled` reads false it calls `upgradeJudgement.stopAll()`, which sets gRPC on directly, without the all-members check. This is what the operator switch does.
- **The write:** `PUT /nacos/v1/ns/operator/switches?entry=...&value=...&debug=...` calls `SwitchManager.update(entry, value, debug)`.
  - `debug=false`, which is what an absent parameter means in the code (a primitive `boolean`), goes through `consistencyService.put`: a replicated write.
  - `debug=true` updates only the local `SwitchDomain`, with no Raft write, so it needs no quorum.
  - Nacos's Open API doc says `debug` means "if affect the local server" and defaults to true. The code disagrees on the default, so pass it explicitly.
- **Correction:** the handoff said the switch "lives in memory only". That was an assumption, written on 2026-09-26 and never tested. The write is replicated, but the chart mounts no volume, so a restarted container starts at the default `true` unless its peers replay the value to it (unmeasured). After a box reboot all three members start at `true`. Every live PUT so far omitted `debug`, so the `debug=true` path hasn't run live.

## Why the hook sends the peer User-Agent

A hook that simply waited for the switch deadlocked every fresh install (found in review; the chain below is from the 2.0.1 source):
1. `TrafficReviseFilter` guards `/v1/ns/*`, which includes `/v1/ns/operator/switches`. Unless the member's status is UP, it answers 503, except to requests whose User-Agent starts with `Nacos-Server` (`sys/env/Constants.NACOS_SERVER_HEADER`).
2. `ServerStatusManager` sets UP only when the consistency service is available. For Distro that needs `distroProtocol.isInitialized()`, because the image's `application.properties` sets `nacos.naming.data.warmup=true` (the code default is false).
3. `DistroLoadDataTask` retries forever until another member answers with a snapshot. It has no "alone" fallback. On the live run a member with no live peers still answered "server is DOWN now ... Distro protocol is not initialized" after 7 min.
4. Under `OrderedReady`, nacos-1 is created only once nacos-0 is Ready, and a container isn't Running until its postStart hook returns. So nacos-0's hook could never succeed.

The switch GET and PUT only touch the member's own `SwitchDomain` (with `debug=true`), so going through the filter's peer path skips no real consistency requirement. `DistroFilter` passes requests whose handler isn't `@CanDistro`, and `updateSwitch` isn't. The probes themselves don't deadlock: `/v1/console/health/*` is outside the filter, and readiness calls `metrics()` in-process, which returns the status without failing.

## Probes and the image

- **Health endpoints** (the same in 2.0.1 and 2.5.4):
  - `/nacos/v1/console/health/liveness` always returns 200 "OK".
  - `/nacos/v1/console/health/readiness` checks a config count in the database plus the naming status string (`metrics` with `onlyStatus=true`). Neither depends on the other members.
- **nacos-k8s**, the official Kubernetes deployment:
  - Its 2.x-era chart (`6fce81c568`, 2022-12) has a startup probe on the readiness endpoint (initial delay 180 s, period 5 s, timeout 10 s), a liveness probe on the liveness endpoint (initial delay 10 s, period 5 s, timeout 10 s), and no readiness probe.
  - The current chart (2026-08) probes `/nacos/` for 2.x and `/v3/console/health/*` on the console port for 3.x. Its default `podManagementPolicy` is `OrderedReady`; its example manifests under `deploy/` use `Parallel`.
- **Kubernetes documentation:**
  - Startup probes: "set up a startup probe with the same command, HTTP or TCP check, with a `failureThreshold * periodSeconds` long enough to cover the worst case startup time."
  - Lifecycle hooks: "If either a PostStart or PreStop hook fails, it kills the Container." Also, the container "may not transition to `Running` until the hook completes", and "Users should make their hook handlers as lightweight as possible. There are cases, however, when long running commands make sense".
- **Finding #22's mechanism:** the 2.0.1 image's entrypoint runs `nohup $JAVA ...` in the foreground (nacos-docker branch `2.0.1`), so the container lives exactly as long as the JVM.
  - On the box, after "Nacos failed to start" the pod stayed `1/1 Running` with 0 restarts, and port 8848 refused connections for at least 4 min.
  - The review reproduced this with the 2.0.1 image: a startup failure logged "Nacos failed to start" while the container stayed up.
  - On #8's inotify failure, by contrast, the JVM exited and the container restarted.
  - The 2.1.2+ images `exec` Java, which would behave the same way, so the probes are needed on every version.
- **Tools in the 2.0.1 image** (checked in review): `/bin/sh` is bash, and curl 7.29.0, GNU grep 2.20 and coreutils `seq` 8.22 are present.
- **Start times on the live run** (container start to 8848 answering, loaded node, upper bounds): 198 s, 3 min 43 s, 4 min 56 s and 6 min 7 s.
- **Init SQL:** `codewisdom/mysqlclient:0.1` is a third-party image whose source isn't in the repo.
  - `/init/init.sh` runs `mysql ... --execute='source /init/nacos-mysql.sql'`.
  - The file has 12 plain `CREATE TABLE`s (no `IF NOT EXISTS`) and the default user.
  - Re-running it is harmless.
    - The review ran it twice against MySQL 5.7 locally, as root: the second run printed 14 `ERROR 1050`/`1062` lines and exited 0, because `source` doesn't turn statement errors into an exit code.
    - On the box, pods 1 and 2 of every install got past it after pod 0 had created the tables.
  - To test a liveness restart, kill Java inside the container: a container restart is what the probe triggers.

## Options for restart safety

1. **Probes only.** A restarted member comes back with double write on and refuses gRPC registrations. It still passes both probes (readiness checks the database and a status string, not the mode), so it stays in the Service. Nothing catches it:
   - no monitor watches Nacos;
   - `test` exercises voucher, which isn't on Nacos;
   - Terraform turns the switch off only when `up` runs again.

   The symptom surfaces later, as unrelated services crash-looping with "Client not connected" on their next restart.
2. **Probes plus a postStart hook (chosen).** On every container start the hook waits for the HTTP port, PUTs `doubleWriteEnabled=false&debug=true` locally with the peer User-Agent, and reads it back.
   - A failed hook kills the container, like a failed startup probe.
   - `debug=true` needs no quorum, which matters when member 0 starts alone under `OrderedReady`.
   - It also covers a box reboot, which until now needed `up` to run again.
3. **A sidecar that re-applies the switch in a loop.** Rejected: it polls forever for state that is lost only when the container starts.
4. **Upgrade Nacos** (below). Dropped.

**Accepted risks of option 2:**
- The three members now start one after another (a real Ready gates the next one). With single starts of up to 3 to 6 min on a loaded node, expect `up` to take 5 to 10 min longer (inferred).
- The hook blocks for about Nacos's start time, and the container shows as not Running meanwhile.
- The hook's and the startup probe's budgets (10 min each) run back to back. Three members at their worst would exceed the release's 30 min Helm timeout. The budgets were borrowed from the MySQL startup probe; the live proof should set them from measured starts.
- No Datadog monitor watches Nacos itself, before or after this change (review D1, deferred to the backlog).

## Upgrade assessment

| | 2.1.2 | 2.5.4 | 3.2.4 |
|---|---|---|---|
| Released | 2022-10-17 | 2026-08-27 | 2026-08-27 (3.3.0-RC on 2026-09-21) |
| 1.x double write | off by default (#7930): with `nacos.core.support.upgrade.from.1x` false, the `UpgradeJudgement` constructor sets gRPC on and never starts the checker | code removed (2.2.0) | code removed: no `UpgradeJudgement` or `DoubleWriteEventListener` in the tree |
| Schema vs the baked 2.0 file | `encrypted_data_key` on `config_info`, `config_info_beta`, `his_config_info` | new `config_info_gray`; `config_info` + `encrypted_data_key`; `his_config_info` + `encrypted_data_key`, `ext_info`, `gray_name`, `publish_type`; the fresh schema no longer creates `config_info_aggr`, `config_info_beta`, `config_info_tag` | 2.5.4's plus `ai_resource`, `ai_resource_version`, `pipeline_execution` |
| Image settings | not checked | same `MYSQL_SERVICE_*`, `MODE`, `NACOS_SERVERS`, `PREFER_HOST_MODE`; the empty token key is fatal only when auth is on (`JwtTokenManager`) | the same, plus `NACOS_AUTH_TOKEN` (Base64, at least 32 characters), `NACOS_AUTH_IDENTITY_KEY` and `NACOS_AUTH_IDENTITY_VALUE`, or the image exits 255; auth on for the console, admin and internal APIs, off for the client API; console on port 8080 |
| Probe endpoints | `/nacos/v1/console/health/*` | `/nacos/v1/console/health/*` (still present) | `/v3/console/health/*` on the console port (nacos-k8s) |
| JDBC driver / JVM defaults | not checked | `mysql-connector-j` 8.2.0 / 1g heap | `mysql-connector-j` 8.2.0 / 1g heap; JDK 17 and Spring Boot 3.5 in the server |

**What every upgrade needs:**
- The image tag, set from Terraform so the vendored chart renders unchanged by default.
- A new init step: the official `mysql` image applying the target's official schema file (kept in the chart), and skipping it when the tables already exist.
- Removing `nacos_double_write_off` and its tests.
- The same probes.
- One live run.

**What no upgrade needs:**
- **Data migration.** The services use Nacos only to find each other, and those registrations live in Nacos's memory. MySQL holds only unused config tables and the default user (cluster mode uses external MySQL by default: "External data sources are used by default in cluster mode", `DatasourceConfiguration`). An existing lab moves over with `down` and `up`.

**Clients:**
- The upstream v1.0.0 images carry Spring Cloud Alibaba 2.2.7.RELEASE, which is Nacos client 2.0.3. The 1.0.1 images are inferred to be the same.
- Our lab images and xlab's `sregym` images carry 2021.0.5.0, which is client 2.2.0.
- Voucher and avatar are Python and don't use Nacos.
- Nacos's 3.0 upgrade doc: client "2.x | Yes"; "1.x | Yes | Support will be removed after v3.2".

**Unverified:** that the Nacos database (Percona 5.7.34) is supported, and Nacos's memory use on 3.x (it adds a console and an AI registry to the same JVM; the box is at 23.5 of 31 GiB).

## What an upgrade would and wouldn't fix

| Problem (finding) | Fixed by upgrading? |
|---|---|
| #12: 1.x double-write mode; the switch lost on a restart or reboot | yes |
| #22: a failed Nacos is never restarted | no: the probes fix it, on any version |
| #3, #20, #21: the Nacos database (three MySQL pods plus xenon) without a leader, half-initialised, or leaderless for a while | no: that's the database |
| #1: slow `up` (MySQL, then Nacos, start in order) | no |
| #8: node inotify limits | no: `WatchFileCenter` is still in 3.2.4 |
| #26: memory (the three Nacos pods use about 5.2 GiB) | no, maybe worse |
| services fail to start while Nacos is unreachable ("Client not connected") | no: that's the client in each service |

Option 2 covers #12's restart and reboot risk too, so the upgrade would buy only maintenance runway. Revisit it if a 2.0.1 bug beyond #12 or a security issue bites, or together with the embedded-storage lever below.

## Unresearched lever: embedded storage

Most of the Nacos pain is the database under it.
- nacos-k8s's chart defaults to `storage.type: embedded`: the members keep their data among themselves over Raft, with no external MySQL.
- The image switches to it with `EMBEDDED_STORAGE=embedded`.
- Dropping the Nacos database would take #3, #20 and #21 out of Nacos's path, save its three MySQL pods, and shorten `up`. `tsdb`, the app's database, stays, so the MySQL/xenon fixes remain.

**Open questions:**
- Whether a first start with members coming up one at a time can reach the Raft majority that embedded storage needs.
- Behaviour after restarts with nothing stored.
- Memory.
- It departs from upstream's deployment (Nacos on MySQL).

A bigger alternative is the parked Kubernetes-native routing spike (`lab/HANDOFF.md`).

## Sources

- alibaba/nacos at tags `2.0.1`, `2.1.0`, `2.5.4`, `3.2.4`: `GrpcRequestFilter`, `TrafficReviseFilter`, `DistroFilter`, `ServerStatusManager`, `DistroLoadDataTask`, `sys/env/Constants`, `UpgradeJudgement`, `DoubleWriteEventListener`, `SwitchManager`, `OperatorController`, `HealthController`, `DatasourceConfiguration`, `JwtTokenManager`, `pom.xml`, `mysql-schema.sql` (3.2.4: `plugin-default-impl/nacos-default-datasource-plugin/nacos-datasource-plugin-mysql/src/main/resources/META-INF/mysql-schema.sql`); release notes of 2.1.0 and 3.0.0.
- nacos-group/nacos-docker at `2.0.1`, `v2.1.2`, `v2.5.4`, `v3.2.4`: `build/Dockerfile`, `build/bin/docker-startup.sh`, `build/conf/application.properties`.
- nacos-group/nacos-k8s: `helm/templates/statefulset.yaml` (current and `6fce81c568`), `helm/values.yaml`, `deploy/nacos/nacos-pvc-nfs.yaml`.
- nacos-group.github.io: `docs/v1/en/open-api.md` ("Update system switch"), `docs/v3.0/en/manual/admin/upgrading.mdx`.
- kubernetes/website: `concepts/containers/container-lifecycle-hooks.md`, `concepts/workloads/pods/pod-lifecycle.md`.
- alibaba/spring-cloud-alibaba `spring-cloud-alibaba-dependencies/pom.xml` at `2.2.7.RELEASE` and `2021.0.5.0`; this repo's `pom.xml` at `v1.0.0`.
- Docker Hub `codewisdom/mysqlclient:0.1`: image config and its two `/init` layers.
