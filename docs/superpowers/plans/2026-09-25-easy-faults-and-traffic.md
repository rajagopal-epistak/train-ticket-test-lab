# Easy Faults and Steady Traffic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development, in the four batches under "Orchestration shape", to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make eight Train-Ticket wiki faults (F1, F3, F7, F12, F14, F15, F17, F22) switchable on this xlab-based fork, and ship a steady traffic driver whose logs show each fault's effect. With every fault off, nothing behaves differently from today.

**Architecture:** Code faults sit behind xlab's existing flagd flags `tt-feat-NN` (all default off), in five rebuilt Java services and the Python voucher service. F3 and F15 are deploy-time patches applied by one toggle script, `lab/fault.sh`. A verbatim copy of auto-query drives the traffic, and a response hook logs one JSON outcome line per HTTP call. GitHub Actions builds the six services and the driver to public GHCR, and `make deploy` picks them up through image overrides in `deploy.yaml.sample`.

**Tech Stack:** Java 8, Spring Boot 2.7.18, OpenFeature SDK 1.4.0 with flagd provider 0.5.4, JUnit 5 and Mockito, flagd v0.11.1, Python 3.12 with requests 2.32.3 and pytest, bash with kubectl, GitHub Actions, GHCR.

**Spec:** There is no separate spec document. The ratified design is in "Fault design" and "Global Constraints" below.

## Orchestration shape

- Build: superpowers:subagent-driven-development in four sequential batches, Tasks 0–2, 3–5, 6–8 and 9–12. Each batch gets one builder (Sonnet, xhigh effort) and then one batch reviewer (Sonnet, medium effort), with scoped fix rounds for confirmed findings.
  - The controller session is started at the repo root with the owner's jdtls-lombok plugin, so jdtls imports the Maven project with the Lombok agent and reports full Java diagnostics.
- Review: 1 deep reviewer, Sonnet, xhigh effort, over the whole branch diff after Task 12. A fix round follows only for confirmed findings.
- Estimate: 2.5–3M tokens. Token ceiling: 3M, hard.

## Global Constraints

- Repo is `/Users/barath/Documents/barath/work/train-ticket-test-lab`, on branch `lab/easy-faults`. That branch was already created from local `master`, which was fast-forwarded to xlab-uiuc `c9537c15`.
  - Never push, merge, amend or rebase.
  - Never commit to `master`.
- The host is a real macOS arm64 machine.
  - Containers run only through `podman`.
  - The host's only JDK is Temurin 21 from mise's global config, and it exists only to run jdtls 1.61.0 (also from mise). There is no Maven, kubectl or helm on the host.
  - Build and test Java only through `hack/lab/mvn.sh` (created in Task 0).
  - Nothing is deployed and no cluster is contacted during this build.
- **Java LSP (jdtls).** Work on Java through the `LSP` tool:
  - `documentSymbol` to locate the methods and fields a step names;
  - `goToDefinition` and `findReferences` before changing a call site or signature;
  - grep for discovery only.

  After every Java edit, read the diagnostics Claude Code reports for that file, and fix every new error before running Maven. Pre-existing warnings are out of scope. jdtls resolves dependencies into the host `~/.m2` by itself; that is expected. If jdtls says a file "is a non-project file, only syntax errors are reported", stop and report: the session was started outside the repo.
- **Flags off must equal today.** With every `tt-feat-*` flag off, and no F3/F15 patch applied, each changed service runs its pre-change logic.
  - The only addition is the flag lookup.
  - Each fault branch hangs off exactly one `featureFlagService.isEnabled("tt-feat-NN")` check.
- Flags are xlab's existing `tt-feat-01`…`tt-feat-22` in `templates/flagd-config.yaml`. Do not add, rename or re-type flags, and do not edit that file.
- Touch only the files listed in each task's **Files** block.
  - Leave xlab's Helm chart alone: `Chart.yaml`, `values.yaml`, `templates/`.
  - Also leave `deploy-job/`, `hack/deploy/`, `Makefile`, both existing workflows, and every existing JUnit 4 test untouched.
  - Dead code you notice (e.g. `ts-cancel-service/src/main/java/cancel/async/AsyncTask.java`, never called) goes in the final report, not the bin.
- New Java tests use JUnit 5 (`org.junit.jupiter`) with `@ExtendWith(MockitoExtension.class)` and `@MockitoSettings(strictness = Strictness.LENIENT)`.
  - The existing JUnit 4 tests are silently skipped by this build (Spring Boot 2.7's starter-test has no vintage engine), so a JUnit 4 test "passing" proves nothing.
- Test evidence: every test run must print `Tests run: N` with N ≥ 1 for the named classes, and then `BUILD SUCCESS`. Exit codes alone are not evidence.
- Build every flagd provider as `new FlagdProvider("flagd", 8013, false, null)`, like xlab's cancel and contacts services. The no-arg constructor falls back to `localhost` and silently turns every flag off.
- No log line may announce an injected fault. xlab removed theirs in `96d37fce`. Faults must be found from behaviour. Ordinary business logs the real bug would emit (e.g. a rejection reason) are fine.
- Service images: `ghcr.io/rajagopal-epistak/<module>:lab` and `:sha-<commit>`, linux/amd64 only. Driver image: `ghcr.io/rajagopal-epistak/tt-traffic-driver:lab`.
- Namespace is `train-ticket`: xlab's flag ConfigMap hard-codes it, and services reach flagd at `flagd:8013`.
- auto-query source: `https://github.com/FudanSELab/train-ticket-auto-query` at `9d5bc2d7a1e7dd6f3ef37b85d04a9fec57d322df`. Copy it unmodified.
- auto-query's `utils.random_str()` and `utils.random_phone()` have no `return` statement, so they always return `None`. Lab code must not call them.
- Commits:
  - One commit per task, conventional type with scope `lab`.
  - Before each commit, run `git diff --staged`.
  - Stage files by name; never `git add .` or `git add -A`.
  - No `Co-Authored-By` or any other trailer, and no mention of Claude or AI in commits or files.
- Action versions (latest releases, checked 2026-09-25): `actions/checkout@v7`, `actions/setup-java@v6`, `docker/setup-buildx-action@v4`, `docker/login-action@v4`, `docker/build-push-action@v7`.
- Python tests: `uv run --no-project --with pytest==8.3.3 --with pyyaml==6.0.2 --with requests==2.32.3 --with tornado==6.5.10 --with pymysql==1.2.3 pytest <paths> -q` from the repo root.

## Fault design

| Fault | Where | When on | When off |
|---|---|---|---|
| F1 | ts-cancel-service `CancelServiceImpl` | `tt-feat-01`: cancel reports the refund done right after the order is set to CANCEL. The refund (`drawbackMoney`) runs on a background thread 8 s later, so events arrive out of order. | synchronous refund, as today |
| F3 | Deployments `ts-train-service`, `ts-basic-service`, `ts-order-service`, `ts-order-other-service` (the four the original misconfigured) | `lab/fault.sh on F3`: container command `java -Xms1g -Xmx1g -jar /app/<service>-1.0.jar`, memory limit 640Mi. The heap is bigger than the limit, so pods are periodically OOMKilled under traffic. The patch sets `command`, not `args`, so it works whether an image starts with `CMD` or `ENTRYPOINT`. | no command override, limit 2000Mi |
| F7 | ts-inside-payment-service and ts-payment-service | `tt-feat-07`: inside-payment always takes the third-party path (ts-payment-service) with a 2 s budget, and payment-service answers after 1.5–2.5 s. About half the pays return HTTP 500. | balance decides the path; no budget, no delay |
| F12 | ts-order-other-service `saveChanges` | `tt-feat-12`: a change to status CANCEL is rejected with `status 0` and "Order cancel rejected: station locked" when from or to is Shanghai or Nanjing (stations locked by an admin). As in the original, it hits K/Z/T-series orders, which cancel-service sends to order-other-service; the driver books those from Shang Hai to Nan Jing. | accepted |
| F14 | ts-basic-service `BasicServiceImpl` | `tt-feat-14`: economy (second-class) fare = distance instead of distance × configured rate | configured rate |
| F15 | Deployment `ts-ui-dashboard` | `lab/fault.sh on F15`: `client_max_body_size 300;` in nginx `location /api/v1/`, via a ConfigMap mount. Bookings with food (330 B) or consign (335 B) get HTTP 413, while plain bookings (238 B) pass, as in the original. The original's 200 B limit would now block every booking. | mount removed |
| F17 | ts-voucher-service (xlab's code, now built by us) | `tt-feat-17`: `SELECT SLEEP(10)` before each voucher lookup | as today |
| F22 | ts-voucher-service `fetchVoucherByOrderId` | `tt-feat-22`: the voucher lookup names a column the `voucher` table lacks (`orderId` instead of `order_id`), so MySQL raises "Unknown column" and `/getVoucher` fails. Print Voucher then shows "Empty. No data!", as in the wiki. xlab's contacts-service variant is not deployed; contacts runs its upstream image. | as today |

## Review Focus

1. **flagd unreachable or down.** Every flag reads as off, no request fails, and no exception escapes a service. Pinned by the `FeatureFlagServiceTest` cases in Task 1 and Task 3.
2. **Station spellings for F12.** The UI and driver send "Shang Hai"; admin data may say "shanghai". Every spelling is recognised. Unrelated stations, and non-cancel updates such as rebook's CHANGE, are never blocked. Pinned by the Task 2 tests.
3. **F7 when the balance already forces the third-party path.** With the flag off, the original unbudgeted call is kept. With it on, the 2 s budget applies whichever way the path was chosen. Pinned by the Task 4 tests.
4. **Toggle idempotency and isolation.** Flipping one flag leaves the other 21 unchanged. The F15 transform inserts exactly one directive, and `on` twice must not insert a second, because nginx refuses to start with a duplicate `client_max_body_size`. Pinned by the Task 8 tests plus the live-check guard in `f15 on`.
5. **Driver resilience.** A non-JSON body, a JSON list, an HTTP 413/500, or a trips response with blank or missing prices still logs one outcome and never crashes the loop. Outcome fields avoid Datadog's reserved attribute names (`status`, `msg`, `message`, `level`, `severity`). Pinned by the Task 9 tests.

---

### Task 0: Build primitive and project notes

**Files:**
- Create: `hack/lab/mvn.sh`
- Create: `CLAUDE.md`
- Add: `docs/superpowers/plans/2026-09-25-easy-faults-and-traffic.md` (this plan, already on disk, uncommitted)

**Interfaces:**
- Produces: `hack/lab/mvn.sh <module> <maven args…>`. It streams the root pom, every module pom, `ts-common` and `<module>` (tracked plus untracked, non-ignored files) into `docker.io/library/maven:3.9-eclipse-temurin-8`, then runs `mvn -B -pl <module> -am <args>`. The Maven cache lives in the podman volume `tt-m2`. The podman VM mounts no host folders, so bind mounts are impossible.

- [ ] **Step 1: Confirm the starting state**

Run: `cd /Users/barath/Documents/barath/work/train-ticket-test-lab && git branch --show-current && git log --oneline -1 && git status --short`

Expected: `lab/easy-faults`, then `c9537c15 Merge pull request #12 from Saadmrp1038/fix-train-ticket-flag-names`, then only `?? docs/`. If anything differs, stop and report.

- [ ] **Step 2: Write `hack/lab/mvn.sh`**

```bash
#!/usr/bin/env bash
# Run Maven for one service module inside the official maven Java 8 image.
# The podman VM mounts no host folders, so the needed sources are streamed in over tar.
# Usage: hack/lab/mvn.sh <module> <maven args...>
#   e.g. hack/lab/mvn.sh ts-order-other-service test -Dtest=OrderOtherServiceImplF12Test -Dsurefire.failIfNoSpecifiedTests=false
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
module="$1"
shift
git ls-files -z --cached --others --exclude-standard -- pom.xml '*/pom.xml' ts-common "$module" \
  | COPYFILE_DISABLE=1 tar --no-mac-metadata --no-xattrs --null -T - -cf - \
  | podman run -i --rm -v tt-m2:/root/.m2 docker.io/library/maven:3.9-eclipse-temurin-8 \
      sh -c 'mkdir /src && cd /src && tar -xf - && mvn -B -pl "$0" -am "$@"' "$module" "$@"
```

Run: `chmod +x hack/lab/mvn.sh`

- [ ] **Step 3: Prove the primitive works**

Run: `hack/lab/mvn.sh ts-basic-service test 2>&1 | grep -E "Building ts-|Tests run:|BUILD|ERROR"`

Expected: `Building ts-common`, then `Building ts-basic-service`, then `BUILD SUCCESS`. There is no `Tests run:` line, because the module's JUnit 4 tests are skipped; that is the known baseline.

- [ ] **Step 4: Prove jdtls has imported the Maven project**

In `ts-basic-service/src/main/java/fdse/microservice/service/BasicServiceImpl.java`, use the `LSP` tool:
- `goToDefinition` at line 7, character 30 (`Response` in `import edu.fudan.common.util.Response;`);
- `hover` at line 17, character 39 (`RestTemplate`).

Expected:
- The definition is in `ts-common/src/main/java/edu/fudan/common/util/Response.java`. That proves cross-module resolution.
- The hover shows `org.springframework.web.client.RestTemplate` type information. That proves dependency resolution.
- The diagnostics for `BasicServiceImpl.java` show no Java errors. That proves jdtls runs with the Lombok agent. An error such as "The method setMsg(String) is undefined for the type Response" means it does not: stop and report.

The first import can take several minutes. If a call times out or finds nothing, run Step 3's command again, then retry. If jdtls reports "non-project file", or the definition still fails, stop and report.

- [ ] **Step 5: Write `CLAUDE.md`**

```markdown
# Train-Ticket fault lab

Fork of FudanSELab/train-ticket, fast-forwarded onto xlab-uiuc/train-ticket (flagd-guarded faults). Lab additions live in `lab/`, `hack/lab/`, `deployment/lab/`, `traffic-driver/` and `.github/workflows/lab-images.yaml`; `lab/README.md` lists the faults.

- Runs on a real host (macOS arm64). Containers: podman only, never Docker Desktop. Never mount the home directory into a VM.
- The host's only JDK is mise's Temurin 21, and it exists only to run jdtls. There is no Maven, kubectl or helm on the host. Build and test Java only through `hack/lab/mvn.sh <module> <maven args>`.
- Java: navigate with the LSP (jdtls), and check its diagnostics after every edit. Start Claude Code at the repo root so jdtls imports the Maven project. jdtls must run with the Lombok javaagent; without it every Lombok accessor reads as undefined.
- Python tests: `uv run --no-project --with pytest==8.3.3 --with pyyaml==6.0.2 --with requests==2.32.3 --with tornado==6.5.10 --with pymysql==1.2.3 pytest lab traffic-driver ts-voucher-service/tests -q`.
- The existing JUnit 4 tests under `ts-*/src/test` never run (Spring Boot 2.7 starter-test has no vintage engine). Write new tests in JUnit 5.
- Faults: flag-driven ones read flagd at `flagd:8013` (ConfigMap `flagd-config`, namespace `train-ticket`) and default to off. With every flag off the services must behave exactly as upstream/xlab.
- Never push, merge or amend without the owner's explicit confirmation. Stage files by name. No trailers and no AI/Claude mentions in commits.
```

- [ ] **Step 6: Commit**

```bash
git add hack/lab/mvn.sh CLAUDE.md docs/superpowers/plans/2026-09-25-easy-faults-and-traffic.md
git diff --staged --stat
git commit -m "chore(lab): add podman maven wrapper, lab notes and build plan"
```

---

### Task 1: F14 — flag-guarded economy fare in ts-basic-service

**Files:**
- Create: `ts-basic-service/src/main/java/fdse/microservice/service/FeatureFlagService.java`
- Modify: `ts-basic-service/src/main/java/fdse/microservice/BasicApplication.java` (flagd provider)
- Modify: `ts-basic-service/src/main/java/fdse/microservice/service/BasicServiceImpl.java` (field, two economy computations, new method)
- Test: `ts-basic-service/src/test/java/fdse/microservice/service/BasicServiceImplF14Test.java`
- Test: `ts-basic-service/src/test/java/fdse/microservice/service/FeatureFlagServiceTest.java`

**Interfaces:**
- Produces:
  - `fdse.microservice.service.FeatureFlagService#isEnabled(String flagName): boolean`. It returns false on any error, when no client exists, and when flagd is unreachable.
  - `BasicServiceImpl#economyPrice(int distance, double basicPriceRate): double`, package-private.

- [ ] **Step 1: Write the failing tests**

`ts-basic-service/src/test/java/fdse/microservice/service/BasicServiceImplF14Test.java`:

```java
package fdse.microservice.service;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class BasicServiceImplF14Test {

    @Mock
    private FeatureFlagService featureFlagService;

    @InjectMocks
    private BasicServiceImpl basicService;

    @Test
    void economyUsesConfiguredRateWhenFlagOff() {
        when(featureFlagService.isEnabled("tt-feat-14")).thenReturn(false);
        assertEquals(38.0, basicService.economyPrice(100, 0.38), 1e-9);
    }

    @Test
    void economyEqualsDistanceWhenFlagOn() {
        when(featureFlagService.isEnabled("tt-feat-14")).thenReturn(true);
        assertEquals(100.0, basicService.economyPrice(100, 0.38), 1e-9);
    }
}
```

`ts-basic-service/src/test/java/fdse/microservice/service/FeatureFlagServiceTest.java`:

```java
package fdse.microservice.service;

import dev.openfeature.contrib.providers.flagd.FlagdProvider;
import dev.openfeature.sdk.OpenFeatureAPI;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;

class FeatureFlagServiceTest {

    @Test
    void readsOffBeforeInitialisation() {
        assertFalse(new FeatureFlagService().isEnabled("tt-feat-14"));
    }

    @Test
    void readsOffWhenFlagdIsUnreachable() {
        OpenFeatureAPI.getInstance().setProvider(new FlagdProvider("127.0.0.1", 1, false, null));
        FeatureFlagService service = new FeatureFlagService();
        service.initialize();
        assertFalse(service.isEnabled("tt-feat-14"));
    }
}
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `hack/lab/mvn.sh ts-basic-service test -Dtest='BasicServiceImplF14Test,FeatureFlagServiceTest' -Dsurefire.failIfNoSpecifiedTests=false 2>&1 | grep -E "Tests run:|BUILD|ERROR" | head -20`

Expected: `COMPILATION ERROR` naming `FeatureFlagService` or `economyPrice`, then `BUILD FAILURE`. If it fails for another reason, stop and report.

- [ ] **Step 3: Write `FeatureFlagService`**

Model it on xlab's `cancel.service.FeatureFlagService`, with basic-service's own client name.

```java
package fdse.microservice.service;

import dev.openfeature.sdk.Client;
import dev.openfeature.sdk.FlagEvaluationDetails;
import dev.openfeature.sdk.OpenFeatureAPI;
import org.springframework.stereotype.Service;

import javax.annotation.PostConstruct;

@Service
public class FeatureFlagService {

    private Client client;

    @PostConstruct
    public void initialize() {
        try {
            this.client = OpenFeatureAPI.getInstance().getClient("basic-service");
        } catch (Exception e) {
            // flags read as off
        }
    }

    public boolean isEnabled(String flagName) {
        try {
            if (client == null) {
                return false;
            }
            FlagEvaluationDetails<Boolean> details = client.getBooleanDetails(flagName, false);
            if ("ERROR".equals(details.getReason())) {
                return false;
            }
            return Boolean.TRUE.equals(details.getValue());
        } catch (Exception e) {
            return false;
        }
    }
}
```

- [ ] **Step 4: Register the flagd provider in `BasicApplication`**

Add these imports next to the existing ones:

```java
import dev.openfeature.contrib.providers.flagd.FlagdProvider;
import dev.openfeature.sdk.OpenFeatureAPI;
import javax.annotation.PostConstruct;
```

Add this method after the `restTemplate` bean. The file indents with tabs, so keep that.

```java
	@PostConstruct
	public void initializeFeatureFlags() {
		try {
			OpenFeatureAPI.getInstance().setProvider(new FlagdProvider("flagd", 8013, false, null));
		} catch (Exception e) {
			// flags read as off
		}
	}
```

- [ ] **Step 5: Guard both economy computations in `BasicServiceImpl`**

Add the field directly below the existing `private RestTemplate restTemplate;` field:

```java
    @Autowired
    private FeatureFlagService featureFlagService;
```

In `queryForTravel`, replace
`double priceForEconomyClass = distance * priceConfig.getBasicPriceRate();`
with
`double priceForEconomyClass = economyPrice(distance, priceConfig.getBasicPriceRate());`

In `queryForTravels`, replace
`double priceForEconomyClass = distance * basicPriceRate;`
with
`double priceForEconomyClass = economyPrice(distance, basicPriceRate);`

Add this method directly above the `@Override` line that precedes `public Response queryForStationId(`:

```java
    // F14: with tt-feat-14 on, the economy fare ignores the configured rate
    double economyPrice(int distance, double basicPriceRate) {
        return featureFlagService.isEnabled("tt-feat-14") ? distance : distance * basicPriceRate;
    }
```

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `hack/lab/mvn.sh ts-basic-service test -Dtest='BasicServiceImplF14Test,FeatureFlagServiceTest' -Dsurefire.failIfNoSpecifiedTests=false 2>&1 | grep -E "Tests run:|BUILD|ERROR" | head -20`

Expected: `Tests run: 4, Failures: 0, Errors: 0, Skipped: 0`, then `BUILD SUCCESS`.

Run: `grep -nE "distance \* (priceConfig\.getBasicPriceRate\(\)|basicPriceRate)" ts-basic-service/src/main/java/fdse/microservice/service/BasicServiceImpl.java`

Expected: exactly one hit, inside `economyPrice`.

- [ ] **Step 7: Commit**

```bash
git add ts-basic-service/src/main/java/fdse/microservice/service/FeatureFlagService.java \
        ts-basic-service/src/main/java/fdse/microservice/BasicApplication.java \
        ts-basic-service/src/main/java/fdse/microservice/service/BasicServiceImpl.java \
        ts-basic-service/src/test/java/fdse/microservice/service/BasicServiceImplF14Test.java \
        ts-basic-service/src/test/java/fdse/microservice/service/FeatureFlagServiceTest.java
git diff --staged
git commit -m "feat(lab): F14 economy fare ignores the price rate behind tt-feat-14"
```

---

### Task 2: F12 — locked-station cancel rejection in ts-order-other-service

**Files:**
- Create: `ts-order-other-service/src/main/java/other/service/FeatureFlagService.java`
- Modify: `ts-order-other-service/src/main/java/other/OrderOtherApplication.java` (flagd provider)
- Modify: `ts-order-other-service/src/main/java/other/service/OrderOtherServiceImpl.java` (field, `saveChanges` guard, helper)
- Test: `ts-order-other-service/src/test/java/other/service/OrderOtherServiceImplF12Test.java`
- Test: `ts-order-other-service/src/test/java/other/service/FeatureFlagServiceTest.java`

**Interfaces:**
- Produces:
  - `other.service.FeatureFlagService#isEnabled(String): boolean`, with the same contract as Task 1.
  - `OrderOtherServiceImpl#saveChanges`. With `tt-feat-12` on, it rejects a change to `OrderStatus.CANCEL` when from or to is a locked station.
  - `static boolean isLockedStation(String station)`, package-private.

cancel-service calls `PUT /api/v1/orderOtherService/orderOther`, which lands in `saveChanges`, to set CANCEL on K/Z/T-series orders. Those are the orders the original F12 was triggered on (per Hagenberg's notes). ts-order-service is not changed and keeps its upstream image.

- [ ] **Step 1: Write the failing tests**

`ts-order-other-service/src/test/java/other/service/OrderOtherServiceImplF12Test.java`:

```java
package other.service;

import edu.fudan.common.entity.OrderStatus;
import edu.fudan.common.util.Response;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.http.HttpHeaders;
import other.entity.Order;
import other.repository.OrderOtherRepository;

import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class OrderOtherServiceImplF12Test {

    @Mock
    private OrderOtherRepository orderOtherRepository;

    @Mock
    private FeatureFlagService featureFlagService;

    @InjectMocks
    private OrderOtherServiceImpl orderOtherService;

    private static Order order(String from, String to, int status) {
        Order o = new Order();
        o.setId("order-1");
        o.setFrom(from);
        o.setTo(to);
        o.setStatus(status);
        return o;
    }

    private Response save(boolean flag, String from, String to, int newStatus) {
        when(featureFlagService.isEnabled("tt-feat-12")).thenReturn(flag);
        when(orderOtherRepository.findById("order-1"))
                .thenReturn(Optional.of(order(from, to, OrderStatus.PAID.getCode())));
        return orderOtherService.saveChanges(order(from, to, newStatus), new HttpHeaders());
    }

    @Test
    void flagOffCancelsOrderFromLockedStation() {
        Response r = save(false, "Shang Hai", "Nan Jing", OrderStatus.CANCEL.getCode());
        assertEquals(1, r.getStatus().intValue());
        verify(orderOtherRepository).save(any(Order.class));
    }

    @ParameterizedTest
    @ValueSource(strings = {"Shang Hai", "shanghai", "SHANGHAI", "Nan Jing"})
    void flagOnRejectsCancelFromLockedStation(String from) {
        Response r = save(true, from, "Su Zhou", OrderStatus.CANCEL.getCode());
        assertEquals(0, r.getStatus().intValue());
        assertEquals("Order cancel rejected: station locked", r.getMsg());
        verify(orderOtherRepository, never()).save(any(Order.class));
    }

    @Test
    void flagOnRejectsCancelToLockedStation() {
        Response r = save(true, "Su Zhou", "nanjing", OrderStatus.CANCEL.getCode());
        assertEquals(0, r.getStatus().intValue());
    }

    @Test
    void flagOnAllowsCancelBetweenUnlockedStations() {
        Response r = save(true, "Su Zhou", "Wu Xi", OrderStatus.CANCEL.getCode());
        assertEquals(1, r.getStatus().intValue());
    }

    @Test
    void flagOnAllowsNonCancelChangeAtLockedStation() {
        Response r = save(true, "Shang Hai", "Nan Jing", OrderStatus.CHANGE.getCode());
        assertEquals(1, r.getStatus().intValue());
    }
}
```

`ts-order-other-service/src/test/java/other/service/FeatureFlagServiceTest.java`:

```java
package other.service;

import dev.openfeature.contrib.providers.flagd.FlagdProvider;
import dev.openfeature.sdk.OpenFeatureAPI;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;

class FeatureFlagServiceTest {

    @Test
    void readsOffBeforeInitialisation() {
        assertFalse(new FeatureFlagService().isEnabled("tt-feat-12"));
    }

    @Test
    void readsOffWhenFlagdIsUnreachable() {
        OpenFeatureAPI.getInstance().setProvider(new FlagdProvider("127.0.0.1", 1, false, null));
        FeatureFlagService service = new FeatureFlagService();
        service.initialize();
        assertFalse(service.isEnabled("tt-feat-12"));
    }
}
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `hack/lab/mvn.sh ts-order-other-service test -Dtest='OrderOtherServiceImplF12Test,FeatureFlagServiceTest' -Dsurefire.failIfNoSpecifiedTests=false 2>&1 | grep -E "Tests run:|FAIL|BUILD|ERROR" | head -20`

Expected: `COMPILATION ERROR` because `FeatureFlagService` is missing, then `BUILD FAILURE`.

- [ ] **Step 3: Write `FeatureFlagService`**

It is identical to Task 1 Step 3 except for the package line and the client name:

```java
package other.service;

import dev.openfeature.sdk.Client;
import dev.openfeature.sdk.FlagEvaluationDetails;
import dev.openfeature.sdk.OpenFeatureAPI;
import org.springframework.stereotype.Service;

import javax.annotation.PostConstruct;

@Service
public class FeatureFlagService {

    private Client client;

    @PostConstruct
    public void initialize() {
        try {
            this.client = OpenFeatureAPI.getInstance().getClient("order-other-service");
        } catch (Exception e) {
            // flags read as off
        }
    }

    public boolean isEnabled(String flagName) {
        try {
            if (client == null) {
                return false;
            }
            FlagEvaluationDetails<Boolean> details = client.getBooleanDetails(flagName, false);
            if ("ERROR".equals(details.getReason())) {
                return false;
            }
            return Boolean.TRUE.equals(details.getValue());
        } catch (Exception e) {
            return false;
        }
    }
}
```

- [ ] **Step 4: Register the provider in `OrderOtherApplication`**

Add the imports:

```java
import dev.openfeature.contrib.providers.flagd.FlagdProvider;
import dev.openfeature.sdk.OpenFeatureAPI;
import javax.annotation.PostConstruct;
```

Add this method after the `restTemplate` bean. This file indents with four spaces.

```java
    @PostConstruct
    public void initializeFeatureFlags() {
        try {
            OpenFeatureAPI.getInstance().setProvider(new FlagdProvider("flagd", 8013, false, null));
        } catch (Exception e) {
            // flags read as off
        }
    }
```

- [ ] **Step 5: Add the guard to `saveChanges` in `OrderOtherServiceImpl`**

Add the field directly below `private RestTemplate restTemplate;`:

```java
    @Autowired
    private FeatureFlagService featureFlagService;
```

In `saveChanges`, insert this as the first statement of the `else {` branch, before `Order oldOrder = op.get();`:

```java
            if (order.getStatus() == OrderStatus.CANCEL.getCode() && featureFlagService.isEnabled("tt-feat-12")
                    && (isLockedStation(order.getFrom()) || isLockedStation(order.getTo()))) {
                OrderOtherServiceImpl.LOGGER.warn("[saveChanges][Modify Order Fail][Station locked][OrderId: {}]", order.getId());
                return new Response<>(0, "Order cancel rejected: station locked", null);
            }
```

Add the constant and helper directly above the `@Override` line that precedes `public Response saveChanges(`. `java.util.*` is already imported.

```java
    // F12: stations under an admin operation; with tt-feat-12 on, cancels touching them are rejected
    private static final Set<String> LOCKED_STATIONS = new HashSet<>(Arrays.asList("shanghai", "nanjing"));

    static boolean isLockedStation(String station) {
        return LOCKED_STATIONS.contains(station.replace(" ", "").toLowerCase());
    }
```

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `hack/lab/mvn.sh ts-order-other-service test -Dtest='OrderOtherServiceImplF12Test,FeatureFlagServiceTest' -Dsurefire.failIfNoSpecifiedTests=false 2>&1 | grep -E "Tests run:|FAIL|BUILD|ERROR" | head -20`

Expected: `Tests run: 10, Failures: 0, Errors: 0, Skipped: 0`, then `BUILD SUCCESS`.

- [ ] **Step 7: Commit**

```bash
git add ts-order-other-service/src/main/java/other/service/FeatureFlagService.java \
        ts-order-other-service/src/main/java/other/OrderOtherApplication.java \
        ts-order-other-service/src/main/java/other/service/OrderOtherServiceImpl.java \
        ts-order-other-service/src/test/java/other/service/OrderOtherServiceImplF12Test.java \
        ts-order-other-service/src/test/java/other/service/FeatureFlagServiceTest.java
git diff --staged
git commit -m "feat(lab): F12 order-other-service rejects cancels at locked stations behind tt-feat-12"
```

---

### Task 3: F7 part 1 — slow third-party answer in ts-payment-service

**Files:**
- Create: `ts-payment-service/src/main/java/com/trainticket/service/FeatureFlagService.java`
- Modify: `ts-payment-service/src/main/java/com/trainticket/PaymentApplication.java` (flagd provider)
- Modify: `ts-payment-service/src/main/java/com/trainticket/service/PaymentServiceImpl.java` (field, delay at the start of `pay`)
- Test: `ts-payment-service/src/test/java/com/trainticket/service/PaymentServiceImplF7Test.java`
- Test: `ts-payment-service/src/test/java/com/trainticket/service/FeatureFlagServiceTest.java`

**Interfaces:**
- Produces:
  - `com.trainticket.service.FeatureFlagService#isEnabled(String): boolean`, with the same contract as Task 1.
  - With `tt-feat-07` on, `PaymentServiceImpl#pay` answers after 1500–2500 ms.

- [ ] **Step 1: Write the failing tests**

`PaymentServiceImplF7Test.java`:

```java
package com.trainticket.service;

import com.trainticket.entity.Payment;
import com.trainticket.repository.AddMoneyRepository;
import com.trainticket.repository.PaymentRepository;
import edu.fudan.common.util.Response;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.http.HttpHeaders;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class PaymentServiceImplF7Test {

    @Mock
    private PaymentRepository paymentRepository;

    @Mock
    private AddMoneyRepository addMoneyRepository;

    @Mock
    private FeatureFlagService featureFlagService;

    @InjectMocks
    private PaymentServiceImpl paymentService;

    private long timedPay(boolean flag) {
        when(featureFlagService.isEnabled("tt-feat-07")).thenReturn(flag);
        when(paymentRepository.findByOrderId("order-1")).thenReturn(null);
        Payment payment = new Payment();
        payment.setOrderId("order-1");
        payment.setPrice("100.0");
        payment.setUserId("user-1");
        long start = System.nanoTime();
        Response r = paymentService.pay(payment, new HttpHeaders());
        long ms = (System.nanoTime() - start) / 1_000_000;
        assertEquals(1, r.getStatus().intValue());
        return ms;
    }

    @Test
    void flagOffAnswersImmediately() {
        long ms = timedPay(false);
        assertTrue(ms < 500, "took " + ms + " ms");
    }

    @Test
    void flagOnAnswersAfterOneAndAHalfToTwoAndAHalfSeconds() {
        long ms = timedPay(true);
        assertTrue(ms >= 1500 && ms <= 2700, "took " + ms + " ms");
    }
}
```

`FeatureFlagServiceTest.java`: the same content as Task 1's `FeatureFlagServiceTest`, with `package com.trainticket.service;` and flag `"tt-feat-07"`.

```java
package com.trainticket.service;

import dev.openfeature.contrib.providers.flagd.FlagdProvider;
import dev.openfeature.sdk.OpenFeatureAPI;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;

class FeatureFlagServiceTest {

    @Test
    void readsOffBeforeInitialisation() {
        assertFalse(new FeatureFlagService().isEnabled("tt-feat-07"));
    }

    @Test
    void readsOffWhenFlagdIsUnreachable() {
        OpenFeatureAPI.getInstance().setProvider(new FlagdProvider("127.0.0.1", 1, false, null));
        FeatureFlagService service = new FeatureFlagService();
        service.initialize();
        assertFalse(service.isEnabled("tt-feat-07"));
    }
}
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `hack/lab/mvn.sh ts-payment-service test -Dtest='PaymentServiceImplF7Test,FeatureFlagServiceTest' -Dsurefire.failIfNoSpecifiedTests=false 2>&1 | grep -E "Tests run:|FAIL|BUILD|ERROR" | head -20`

Expected: `COMPILATION ERROR` because `FeatureFlagService` is missing, then `BUILD FAILURE`.

- [ ] **Step 3: Write `FeatureFlagService`**

It is identical to Task 1 Step 3 except for the package line (`package com.trainticket.service;`) and the client name (`getClient("payment-service")`).

```java
package com.trainticket.service;

import dev.openfeature.sdk.Client;
import dev.openfeature.sdk.FlagEvaluationDetails;
import dev.openfeature.sdk.OpenFeatureAPI;
import org.springframework.stereotype.Service;

import javax.annotation.PostConstruct;

@Service
public class FeatureFlagService {

    private Client client;

    @PostConstruct
    public void initialize() {
        try {
            this.client = OpenFeatureAPI.getInstance().getClient("payment-service");
        } catch (Exception e) {
            // flags read as off
        }
    }

    public boolean isEnabled(String flagName) {
        try {
            if (client == null) {
                return false;
            }
            FlagEvaluationDetails<Boolean> details = client.getBooleanDetails(flagName, false);
            if ("ERROR".equals(details.getReason())) {
                return false;
            }
            return Boolean.TRUE.equals(details.getValue());
        } catch (Exception e) {
            return false;
        }
    }
}
```

- [ ] **Step 4: Register the provider in `PaymentApplication`**

Add the same three imports and the same tab-indented `initializeFeatureFlags()` method as Task 1 Step 4, after the `restTemplate` bean:

```java
import dev.openfeature.contrib.providers.flagd.FlagdProvider;
import dev.openfeature.sdk.OpenFeatureAPI;
import javax.annotation.PostConstruct;
```

```java
	@PostConstruct
	public void initializeFeatureFlags() {
		try {
			OpenFeatureAPI.getInstance().setProvider(new FlagdProvider("flagd", 8013, false, null));
		} catch (Exception e) {
			// flags read as off
		}
	}
```

- [ ] **Step 5: Add the delay to `PaymentServiceImpl`**

Add `import java.util.concurrent.ThreadLocalRandom;`. Add the field below `AddMoneyRepository addMoneyRepository;`:

```java
    @Autowired
    private FeatureFlagService featureFlagService;
```

Make `thirdPartyDelay();` the first statement of `public Response pay(Payment info, HttpHeaders headers){`, then add this method directly after `pay`:

```java
    // F7: with tt-feat-07 on, this third-party payment answers after 1.5-2.5 s
    private void thirdPartyDelay() {
        if (featureFlagService.isEnabled("tt-feat-07")) {
            try {
                Thread.sleep(1500 + ThreadLocalRandom.current().nextInt(1001));
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }
    }
```

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `hack/lab/mvn.sh ts-payment-service test -Dtest='PaymentServiceImplF7Test,FeatureFlagServiceTest' -Dsurefire.failIfNoSpecifiedTests=false 2>&1 | grep -E "Tests run:|FAIL|BUILD|ERROR" | head -20`

Expected: `Tests run: 4, Failures: 0, Errors: 0, Skipped: 0`, then `BUILD SUCCESS`.

- [ ] **Step 7: Commit**

```bash
git add ts-payment-service/src/main/java/com/trainticket/service/FeatureFlagService.java \
        ts-payment-service/src/main/java/com/trainticket/PaymentApplication.java \
        ts-payment-service/src/main/java/com/trainticket/service/PaymentServiceImpl.java \
        ts-payment-service/src/test/java/com/trainticket/service/PaymentServiceImplF7Test.java \
        ts-payment-service/src/test/java/com/trainticket/service/FeatureFlagServiceTest.java
git diff --staged
git commit -m "feat(lab): F7 payment-service answers slowly behind tt-feat-07"
```

---

### Task 4: F7 part 2 — forced third-party payment with a 2 s budget in ts-inside-payment-service

**Files:**
- Modify: `ts-inside-payment-service/src/main/java/inside_payment/InsidePaymentApplication.java` (provider constructor)
- Modify: `ts-inside-payment-service/src/main/java/inside_payment/service/InsidePaymentServiceImpl.java` (field, `pay` branch, new method)
- Test: `ts-inside-payment-service/src/test/java/inside_payment/service/InsidePaymentServiceImplF7Test.java`

**Interfaces:**
- Consumes: xlab's `inside_payment.service.FeatureFlagService#isEnabled(String): boolean`, which already exists.
- Produces:
  - `InsidePaymentServiceImpl#outsidePayment(String url, HttpEntity request, boolean budgeted): ResponseEntity<Response>`, package-private.
  - `static final long OUTSIDE_PAYMENT_BUDGET_MS = 2000`.
  - When the budget is exceeded, `pay` throws `IllegalStateException`, which becomes HTTP 500.

- [ ] **Step 1: Write the failing test**

```java
package inside_payment.service;

import edu.fudan.common.entity.Order;
import edu.fudan.common.entity.OrderStatus;
import edu.fudan.common.util.Response;
import inside_payment.entity.Money;
import inside_payment.entity.PaymentInfo;
import inside_payment.repository.AddMoneyRepository;
import inside_payment.repository.PaymentRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.client.RestTemplate;

import java.util.ArrayList;
import java.util.Collections;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class InsidePaymentServiceImplF7Test {

    private static final String PAYMENT_URL = "http://ts-payment-service/api/v1/paymentservice/payment";

    @Mock
    private RestTemplate restTemplate;

    @Mock
    private PaymentRepository paymentRepository;

    @Mock
    private AddMoneyRepository addMoneyRepository;

    @Mock
    private FeatureFlagService featureFlagService;

    @InjectMocks
    private InsidePaymentServiceImpl service;

    @BeforeEach
    void unpaidOrderAndRichAccount() {
        Order order = new Order();
        order.setStatus(OrderStatus.NOTPAID.getCode());
        order.setPrice("100.0");
        doReturn(new ResponseEntity<>(new Response<>(1, "Success", order), HttpStatus.OK))
                .when(restTemplate).exchange(anyString(), eq(HttpMethod.GET), any(HttpEntity.class), any(ParameterizedTypeReference.class));
        doReturn(new ResponseEntity<>(new Response<>(1, "Success", null), HttpStatus.OK))
                .when(restTemplate).exchange(contains("/status/"), eq(HttpMethod.GET), any(HttpEntity.class), eq(Response.class));
        Money money = new Money();
        money.setUserId("user-1");
        money.setMoney("10000");
        when(paymentRepository.findByUserId("user-1")).thenReturn(new ArrayList<>());
        when(addMoneyRepository.findByUserId("user-1")).thenReturn(Collections.singletonList(money));
    }

    private static PaymentInfo info() {
        PaymentInfo i = new PaymentInfo();
        i.setUserId("user-1");
        i.setOrderId("order-1");
        i.setTripId("G1234");
        return i;
    }

    private void paymentServiceAnswersAfter(long ms) {
        doAnswer(inv -> {
            Thread.sleep(ms);
            return new ResponseEntity<>(new Response<>(1, "Pay Success", null), HttpStatus.OK);
        }).when(restTemplate).exchange(eq(PAYMENT_URL), eq(HttpMethod.POST), any(HttpEntity.class), eq(Response.class));
    }

    @Test
    void flagOffPaysFromBalanceWithoutThirdParty() {
        when(featureFlagService.isEnabled("tt-feat-07")).thenReturn(false);
        Response r = service.pay(info(), new HttpHeaders());
        assertEquals(1, r.getStatus().intValue());
        verify(restTemplate, never()).exchange(eq(PAYMENT_URL), eq(HttpMethod.POST), any(HttpEntity.class), eq(Response.class));
    }

    @Test
    void flagOnForcesThirdPartyAndSucceedsWithinBudget() {
        when(featureFlagService.isEnabled("tt-feat-07")).thenReturn(true);
        paymentServiceAnswersAfter(100);
        Response r = service.pay(info(), new HttpHeaders());
        assertEquals(1, r.getStatus().intValue());
        verify(restTemplate).exchange(eq(PAYMENT_URL), eq(HttpMethod.POST), any(HttpEntity.class), eq(Response.class));
    }

    @Test
    void flagOnFailsWhenThirdPartyExceedsBudget() {
        when(featureFlagService.isEnabled("tt-feat-07")).thenReturn(true);
        paymentServiceAnswersAfter(3000);
        long start = System.nanoTime();
        assertThrows(IllegalStateException.class, () -> service.pay(info(), new HttpHeaders()));
        long ms = (System.nanoTime() - start) / 1_000_000;
        assertTrue(ms < 2800, "took " + ms + " ms");
    }

    @Test
    void flagOffKeepsUnbudgetedCallWhenBalanceIsShort() {
        when(featureFlagService.isEnabled("tt-feat-07")).thenReturn(false);
        when(addMoneyRepository.findByUserId("user-1")).thenReturn(new ArrayList<>());
        paymentServiceAnswersAfter(2500);
        Response r = service.pay(info(), new HttpHeaders());
        assertEquals(1, r.getStatus().intValue());
    }
}
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `hack/lab/mvn.sh ts-inside-payment-service test -Dtest=InsidePaymentServiceImplF7Test -Dsurefire.failIfNoSpecifiedTests=false 2>&1 | grep -E "Tests run:|FAIL|BUILD|ERROR" | head -20`

Expected: `flagOnForcesThirdPartyAndSucceedsWithinBudget` and `flagOnFailsWhenThirdPartyExceedsBudget` fail, then `BUILD FAILURE`.

- [ ] **Step 3: Implement it in `InsidePaymentServiceImpl`**

Add the imports:

```java
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
```

Add the field directly below `public RestTemplate restTemplate;`:

```java
    @Autowired
    private FeatureFlagService featureFlagService;

    static final long OUTSIDE_PAYMENT_BUDGET_MS = 2000;
```

In `pay`, directly before `if (totalExpand.compareTo(money) > 0) {`, insert:

```java
            boolean thirdPartyFault = featureFlagService.isEnabled("tt-feat-07");
```

Then change that line to:

```java
            if (thirdPartyFault || totalExpand.compareTo(money) > 0) {
```

Inside that branch, replace:

```java
                ResponseEntity<Response> reOutsidePaySuccess = restTemplate.exchange(
                        payment_service_url + "/api/v1/paymentservice/payment",
                        HttpMethod.POST,
                        requestEntityOutsidePaySuccess,
                        Response.class);
```

with:

```java
                ResponseEntity<Response> reOutsidePaySuccess = outsidePayment(
                        payment_service_url + "/api/v1/paymentservice/payment",
                        requestEntityOutsidePaySuccess,
                        thirdPartyFault);
```

Add this method directly after `pay`:

```java
    // F7: with tt-feat-07 on, the third-party payment call gets a 2 s budget
    ResponseEntity<Response> outsidePayment(String url, HttpEntity request, boolean budgeted) {
        if (!budgeted) {
            return restTemplate.exchange(url, HttpMethod.POST, request, Response.class);
        }
        try {
            return CompletableFuture
                    .supplyAsync(() -> restTemplate.exchange(url, HttpMethod.POST, request, Response.class))
                    .get(OUTSIDE_PAYMENT_BUDGET_MS, TimeUnit.MILLISECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("Outside payment interrupted", e);
        } catch (ExecutionException | TimeoutException e) {
            throw new IllegalStateException("Outside payment failed: " + e, e);
        }
    }
```

- [ ] **Step 4: Point the provider at flagd in `InsidePaymentApplication`**

Inside `initializeFeatureFlags()`, replace the whole `try` body:

```java
            String flagdHost = System.getenv().getOrDefault("FLAGD_HOST", "flagd");
            int flagdPort = Integer.parseInt(System.getenv().getOrDefault("FLAGD_PORT", "8013"));

            FlagdProvider provider = new FlagdProvider();
            OpenFeatureAPI.getInstance().setProvider(provider);
```

with:

```java
            OpenFeatureAPI.getInstance().setProvider(new FlagdProvider("flagd", 8013, false, null));
```

Leave the file's duplicated import block as it is (pre-existing; note it in the final report).

Run: `grep -n "new FlagdProvider(" ts-inside-payment-service/src/main/java/inside_payment/InsidePaymentApplication.java`

Expected: one hit, `new FlagdProvider("flagd", 8013, false, null)`.

- [ ] **Step 5: Run the test and confirm it passes**

Run: `hack/lab/mvn.sh ts-inside-payment-service test -Dtest=InsidePaymentServiceImplF7Test -Dsurefire.failIfNoSpecifiedTests=false 2>&1 | grep -E "Tests run:|FAIL|BUILD|ERROR" | head -20`

Expected: `Tests run: 4, Failures: 0, Errors: 0, Skipped: 0`, then `BUILD SUCCESS`.

- [ ] **Step 6: Commit**

```bash
git add ts-inside-payment-service/src/main/java/inside_payment/InsidePaymentApplication.java \
        ts-inside-payment-service/src/main/java/inside_payment/service/InsidePaymentServiceImpl.java \
        ts-inside-payment-service/src/test/java/inside_payment/service/InsidePaymentServiceImplF7Test.java
git diff --staged
git commit -m "feat(lab): F7 inside-payment forces a 2 s third-party payment behind tt-feat-07"
```

---

### Task 5: F1 — out-of-order refund in ts-cancel-service

**Files:**
- Modify: `ts-cancel-service/src/main/java/cancel/service/CancelServiceImpl.java` (field, `refund` method, two call sites)
- Test: `ts-cancel-service/src/test/java/cancel/service/CancelServiceImplF1Test.java`

**Interfaces:**
- Consumes: xlab's `cancel.service.FeatureFlagService#isEnabled(String): boolean`, which already exists and whose provider already points at `flagd`.
- Produces:
  - `CancelServiceImpl#refund(String money, String userId, HttpHeaders headers): boolean`, package-private.
  - `long refundDelayMs = 8000`, a package-private field that tests shorten.

xlab's `AsyncTask.drawBackMoneyForOrderCancel` is never called, and it names an executor bean (`mySimpleAsync`) that cancel-service does not define. Leave it untouched and list it in the final report.

- [ ] **Step 1: Write the failing test**

```java
package cancel.service;

import edu.fudan.common.util.Response;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.mockito.verification.VerificationMode;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.client.RestTemplate;

import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.timeout;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class CancelServiceImplF1Test {

    private static final String DRAWBACK_URL =
            "http://ts-inside-payment-service/api/v1/inside_pay_service/inside_payment/drawback/user-1/50.0";

    @Mock
    private RestTemplate restTemplate;

    @Mock
    private FeatureFlagService featureFlagService;

    @InjectMocks
    private CancelServiceImpl cancelService;

    @BeforeEach
    void drawbackSucceeds() {
        doReturn(new ResponseEntity<>(new Response<>(1, "Draw Back Money Success", null), HttpStatus.OK))
                .when(restTemplate).exchange(contains("/drawback/"), eq(HttpMethod.GET), any(HttpEntity.class), eq(Response.class));
    }

    private void verifyDrawback(VerificationMode mode) {
        verify(restTemplate, mode).exchange(eq(DRAWBACK_URL), eq(HttpMethod.GET), any(HttpEntity.class), eq(Response.class));
    }

    @Test
    void flagOffRefundsBeforeReturning() {
        when(featureFlagService.isEnabled("tt-feat-01")).thenReturn(false);
        assertTrue(cancelService.refund("50.0", "user-1", new HttpHeaders()));
        verifyDrawback(times(1));
    }

    @Test
    void flagOnReturnsBeforeTheRefundThenRefundsLater() {
        when(featureFlagService.isEnabled("tt-feat-01")).thenReturn(true);
        cancelService.refundDelayMs = 500;
        assertTrue(cancelService.refund("50.0", "user-1", new HttpHeaders()));
        verifyDrawback(never());
        verifyDrawback(timeout(3000).times(1));
    }
}
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `hack/lab/mvn.sh ts-cancel-service test -Dtest=CancelServiceImplF1Test -Dsurefire.failIfNoSpecifiedTests=false 2>&1 | grep -E "Tests run:|FAIL|BUILD|ERROR" | head -20`

Expected: `COMPILATION ERROR` because `refund` and `refundDelayMs` are missing, then `BUILD FAILURE`.

- [ ] **Step 3: Implement it in `CancelServiceImpl`**

Add `import java.util.concurrent.CompletableFuture;`. Add the fields directly below `private DiscoveryClient discoveryClient;`:

```java
    @Autowired
    private FeatureFlagService featureFlagService;

    long refundDelayMs = 8000;
```

Replace both occurrences of
`boolean status = drawbackMoney(money, loginId, headers);`
with
`boolean status = refund(money, loginId, headers);`

Add this method directly above `public boolean drawbackMoney(`. That method has no annotation.

```java
    // F1: with tt-feat-01 on, the refund runs after the cancel has already reported it (events out of order)
    boolean refund(String money, String userId, HttpHeaders headers) {
        if (!featureFlagService.isEnabled("tt-feat-01")) {
            return drawbackMoney(money, userId, headers);
        }
        CompletableFuture.runAsync(() -> {
            try {
                Thread.sleep(refundDelayMs);
                if (!drawbackMoney(money, userId, headers)) {
                    CancelServiceImpl.LOGGER.error("[refund][Draw Back Money Failed][userId: {}]", userId);
                }
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            } catch (RuntimeException e) {
                CancelServiceImpl.LOGGER.error("[refund][Draw Back Money Failed][userId: {}]", userId, e);
            }
        });
        return true;
    }
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `hack/lab/mvn.sh ts-cancel-service test -Dtest=CancelServiceImplF1Test -Dsurefire.failIfNoSpecifiedTests=false 2>&1 | grep -E "Tests run:|FAIL|BUILD|ERROR" | head -20`

Expected: `Tests run: 2, Failures: 0, Errors: 0, Skipped: 0`, then `BUILD SUCCESS`.

Run: `grep -c "boolean status = refund(money, loginId, headers);" ts-cancel-service/src/main/java/cancel/service/CancelServiceImpl.java`

Expected: `2`.

- [ ] **Step 5: Commit**

```bash
git add ts-cancel-service/src/main/java/cancel/service/CancelServiceImpl.java \
        ts-cancel-service/src/test/java/cancel/service/CancelServiceImplF1Test.java
git diff --staged
git commit -m "feat(lab): F1 cancel reports the refund before it runs behind tt-feat-01"
```

---

### Task 6: F22 — missing-column voucher lookup in ts-voucher-service

**Files:**
- Modify: `ts-voucher-service/server.py` (`fetchVoucherByOrderId`)
- Test: `ts-voucher-service/tests/test_f22.py`

**Interfaces:**
- Consumes: xlab's module-level `feature_flag_service` in `server.py`, which F17 already uses. Its `is_enabled(name) -> bool` returns false on any error.
- Produces: with `tt-feat-22` on, `GetVoucherHandler.fetchVoucherByOrderId` queries `WHERE orderId = %s`.
  - The table's column is `order_id`, so MySQL raises error 1054 ("Unknown column").
  - The handler does not catch it, so `/getVoucher` answers HTTP 500.

The wiki's F22 is Print Voucher showing "Empty. No data!". Hagenberg's F22 notes confirm that "voucher" means receipt here. xlab's F22 in ts-contacts-service stays in the repo but is not deployed; Task 7 reverts contacts to its upstream image.

- [ ] **Step 1: Write the failing test**

`ts-voucher-service/tests/test_f22.py`:

```python
import json
import re
import sys
import types
from pathlib import Path

VOUCHER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(VOUCHER))


class StubFlags:
    enabled = frozenset()

    def is_enabled(self, name):
        return name in self.enabled


# server.py builds its flagd client at import; stub it so the test needs no flagd.
sys.modules["feature_flag_service"] = types.SimpleNamespace(FeatureFlagService=StubFlags)
import server  # noqa: E402

SCHEMA = re.findall(r"^\s+(\w+) (?:INT|VARCHAR|FLOAT)", (VOUCHER / "server.py").read_text(), re.M)
ROW = (7, "o1", "2026-09-26", "09:00", "Contact", "G1234", 2, "5", "Shang Hai", "Su Zhou", 100.0)


class FakeCursor:
    def __init__(self):
        self.sql = None
        self.rowcount = 0

    def execute(self, sql, args):
        self.sql = sql
        self.rowcount = 1

    def fetchone(self):
        return ROW


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def commit(self):
        pass

    def close(self):
        pass


def lookup(monkeypatch, flags):
    cursor = FakeCursor()
    monkeypatch.setattr(server.pymysql, "connect", lambda **kwargs: FakeConnection(cursor))
    monkeypatch.setattr(server.feature_flag_service, "enabled", frozenset(flags))
    result = server.GetVoucherHandler.fetchVoucherByOrderId(None, "o1")
    column = re.search(r"where (\w+) = %s", cursor.sql).group(1)
    return column, result


def test_schema_is_read_from_the_create_table_statement():
    assert "order_id" in SCHEMA and "voucher_id" in SCHEMA


def test_flag_off_looks_up_by_a_real_column_and_returns_the_voucher(monkeypatch):
    column, result = lookup(monkeypatch, [])
    assert column in SCHEMA
    assert json.loads(result)["order_id"] == "o1"


def test_f22_looks_up_by_a_column_the_table_lacks(monkeypatch):
    column, _ = lookup(monkeypatch, ["tt-feat-22"])
    assert column not in SCHEMA


def test_other_flags_leave_the_lookup_alone(monkeypatch):
    column, _ = lookup(monkeypatch, ["tt-feat-17"])
    assert column == "order_id"
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `uv run --no-project --with pytest==8.3.3 --with pyyaml==6.0.2 --with requests==2.32.3 --with tornado==6.5.10 --with pymysql==1.2.3 pytest ts-voucher-service/tests -q`

Expected: `test_f22_looks_up_by_a_column_the_table_lacks` fails; the other three pass.

- [ ] **Step 3: Implement it in `fetchVoucherByOrderId`**

Directly after the line `sql = 'SELECT * FROM voucher where order_id = %s'`, insert (method body, 8 spaces):

```python
        # F-22: with tt-feat-22 on, the lookup names a column the voucher table does not have
        if feature_flag_service.is_enabled("tt-feat-22"):
            sql = 'SELECT * FROM voucher where orderId = %s'
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `uv run --no-project --with pytest==8.3.3 --with pyyaml==6.0.2 --with requests==2.32.3 --with tornado==6.5.10 --with pymysql==1.2.3 pytest ts-voucher-service/tests -q`

Expected: `4 passed`.

- [ ] **Step 5: Prove the image still builds**

This uses xlab's unchanged Dockerfile, as a native arm64 check; CI builds amd64.

Run: `podman build -t localhost/ts-voucher-service:check ts-voucher-service && podman rmi localhost/ts-voucher-service:check`

Expected: the build succeeds and the image is removed.

- [ ] **Step 6: Commit**

```bash
git add ts-voucher-service/server.py ts-voucher-service/tests/test_f22.py
git diff --staged
git commit -m "feat(lab): F22 voucher lookup names a missing column behind tt-feat-22"
```

---

### Task 7: flagd manifest and lab image overrides

**Files:**
- Create: `deployment/lab/flagd.yaml`
- Modify: `deployment/kubernetes-manifests/quickstart-k8s/yamls/deploy.yaml.sample` (image and pull-policy lines of six lab containers, plus the contacts image line; see Step 4)
- Test: `lab/tests/test_manifests.py`

**Interfaces:**
- Produces: Deployment plus Service `flagd` with no namespace field and no RBAC. It serves gRPC on 8013 and OFREP on 8016, and reads ConfigMap `flagd-config`, which the deployer applies from `templates/flagd-config.yaml`.
- `make deploy` deploys the six lab images, and ts-contacts-service runs its upstream image again.

- [ ] **Step 1: Write the failing test**

`lab/tests/test_manifests.py`:

```python
import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SAMPLE = "deployment/kubernetes-manifests/quickstart-k8s/yamls/deploy.yaml.sample"
BASE = "c9537c15"
UPSTREAM = "313886e9"
LAB = {"ts-basic-service", "ts-order-other-service", "ts-inside-payment-service", "ts-payment-service", "ts-cancel-service",
       "ts-voucher-service"}
REVERTED = {"ts-contacts-service"}  # xlab's F22 variant is not deployed; the lab's F22 lives in ts-voucher-service


def containers(text):
    for doc in yaml.safe_load_all(text):
        if doc and doc.get("kind") == "Deployment":
            for c in doc["spec"]["template"]["spec"]["containers"]:
                yield c["name"], c


def test_lab_services_use_lab_images():
    current = dict(containers((REPO / SAMPLE).read_text()))
    for name in LAB:
        assert current[name]["image"] == f"ghcr.io/rajagopal-epistak/{name}:lab"
        assert current[name]["imagePullPolicy"] == "Always"


def sample_at(ref):
    return subprocess.run(["git", "show", f"{ref}:{SAMPLE}"], cwd=REPO, capture_output=True, text=True, check=True).stdout


def test_contacts_runs_the_upstream_image():
    upstream = dict(containers(sample_at(UPSTREAM)))
    current = dict(containers((REPO / SAMPLE).read_text()))
    assert current["ts-contacts-service"] == upstream["ts-contacts-service"]


def test_every_other_deployment_is_unchanged():
    base = dict(containers(sample_at(BASE)))
    current = dict(containers((REPO / SAMPLE).read_text()))
    assert base.keys() == current.keys()
    for name in base.keys() - LAB - REVERTED:
        assert current[name] == base[name], name
    for name in LAB:
        strip = lambda c: {k: v for k, v in c.items() if k not in ("image", "imagePullPolicy")}
        assert strip(current[name]) == strip(base[name]), name


def test_flagd_manifest_is_namespace_free_and_reads_the_flag_configmap():
    docs = [d for d in yaml.safe_load_all((REPO / "deployment/lab/flagd.yaml").read_text()) if d]
    assert sorted(d["kind"] for d in docs) == ["Deployment", "Service"]
    assert all("namespace" not in d["metadata"] for d in docs)
    deployment = next(d for d in docs if d["kind"] == "Deployment")
    pod = deployment["spec"]["template"]["spec"]
    assert "serviceAccountName" not in pod
    assert pod["containers"][0]["image"] == "ghcr.io/open-feature/flagd:v0.11.1"
    assert pod["volumes"][0]["configMap"]["name"] == "flagd-config"
    service = next(d for d in docs if d["kind"] == "Service")
    assert {p["port"] for p in service["spec"]["ports"]} == {8013, 8016}


def test_flag_configmap_starts_with_every_fault_off():
    configmap = yaml.safe_load((REPO / "templates/flagd-config.yaml").read_text())
    flags = yaml.safe_load(configmap["data"]["flags.yaml"])["flags"]
    assert sorted(flags) == [f"tt-feat-{n:02d}" for n in range(1, 23)]
    assert {f["defaultVariant"] for f in flags.values()} == {"off"}
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `uv run --no-project --with pytest==8.3.3 --with pyyaml==6.0.2 --with requests==2.32.3 --with tornado==6.5.10 --with pymysql==1.2.3 pytest lab/tests/test_manifests.py -q`

Expected: `test_lab_services_use_lab_images`, `test_contacts_runs_the_upstream_image` and `test_flagd_manifest_is_namespace_free_and_reads_the_flag_configmap` fail; the other two pass.

- [ ] **Step 3: Write `deployment/lab/flagd.yaml`**

```yaml
# flagd for the `make deploy` path. It serves ConfigMap flagd-config (apply templates/flagd-config.yaml first).
# Container settings match templates/flagd-deployment.yaml; the ServiceAccount and ClusterRole there are dropped
# because flagd only reads the mounted file.
apiVersion: apps/v1
kind: Deployment
metadata:
  name: flagd
  labels:
    app: flagd
spec:
  replicas: 1
  selector:
    matchLabels:
      app: flagd
  template:
    metadata:
      labels:
        app: flagd
    spec:
      containers:
        - name: flagd
          image: ghcr.io/open-feature/flagd:v0.11.1
          args: ["start", "--uri", "file:./etc/flagd/flags.yaml", "--port", "8013", "--ofrep-port", "8016", "--cors-origin", "*"]
          ports:
            - {containerPort: 8013, name: rpc}
            - {containerPort: 8016, name: ofrep}
            - {containerPort: 8014, name: mgmt}
          env:
            - name: FLAGD_LOG_LEVEL
              value: info
          livenessProbe:
            httpGet: {path: /readyz, port: 8014}
            initialDelaySeconds: 10
            periodSeconds: 10
          readinessProbe:
            httpGet: {path: /readyz, port: 8014}
            initialDelaySeconds: 5
            periodSeconds: 5
          volumeMounts:
            - name: config-volume
              mountPath: /etc/flagd
              readOnly: true
      volumes:
        - name: config-volume
          configMap:
            name: flagd-config
---
apiVersion: v1
kind: Service
metadata:
  name: flagd
  labels:
    app: flagd
spec:
  selector:
    app: flagd
  ports:
    - {name: rpc, port: 8013, targetPort: 8013, protocol: TCP}
    - {name: ofrep, port: 8016, targetPort: 8016, protocol: TCP}
```

- [ ] **Step 4: Point six containers in `deploy.yaml.sample` at the lab images, and revert contacts**

In each container block, change only its `image:` and `imagePullPolicy:` lines.

| Container | old `image:` | new `image:` | `imagePullPolicy:` |
|---|---|---|---|
| `ts-basic-service` | `codewisdom/ts-basic-service:1.0.0` | `ghcr.io/rajagopal-epistak/ts-basic-service:lab` | `IfNotPresent` → `Always` |
| `ts-order-other-service` | `codewisdom/ts-order-other-service:1.0.1` | `ghcr.io/rajagopal-epistak/ts-order-other-service:lab` | `IfNotPresent` → `Always` |
| `ts-inside-payment-service` | `codewisdom/ts-inside-payment-service:1.0.0` | `ghcr.io/rajagopal-epistak/ts-inside-payment-service:lab` | `IfNotPresent` → `Always` |
| `ts-payment-service` | `codewisdom/ts-payment-service:1.0.0` | `ghcr.io/rajagopal-epistak/ts-payment-service:lab` | `IfNotPresent` → `Always` |
| `ts-cancel-service` | `ghcr.io/sregym/ts-cancel-service:latest` | `ghcr.io/rajagopal-epistak/ts-cancel-service:lab` | `IfNotPresent` → `Always` |
| `ts-voucher-service` | `ghcr.io/sregym/ts-voucher-service:latest` | `ghcr.io/rajagopal-epistak/ts-voucher-service:lab` | `IfNotPresent` → `Always` |

Revert `ts-contacts-service`. Change only its `image:` line, from `ghcr.io/sregym/ts-contacts-service:latest` to `codewisdom/ts-contacts-service:1.0.0` (the upstream value), and keep `IfNotPresent`.

`Always` is needed because `:lab` moves on every build.

- [ ] **Step 5: Run the test and confirm it passes**

Run: `uv run --no-project --with pytest==8.3.3 --with pyyaml==6.0.2 --with requests==2.32.3 --with tornado==6.5.10 --with pymysql==1.2.3 pytest lab/tests/test_manifests.py -q`

Expected: `5 passed`.

Run: `git diff --stat -- deployment/kubernetes-manifests/quickstart-k8s/yamls/deploy.yaml.sample`

Expected: `1 file changed, 13 insertions(+), 13 deletions(-)`.

- [ ] **Step 6: Commit**

```bash
git add deployment/lab/flagd.yaml deployment/kubernetes-manifests/quickstart-k8s/yamls/deploy.yaml.sample lab/tests/test_manifests.py
git diff --staged
git commit -m "feat(lab): plain flagd manifest and lab image overrides for make deploy"
```

---

### Task 8: Fault toggle script

**Files:**
- Create: `lab/fault.sh`
- Test: `lab/tests/test_fault_sh.py`

**Interfaces:**
- Produces: `lab/fault.sh on|off|status F1|F3|F7|F12|F14|F15|F17|F22`, with env `NAMESPACE` (default `train-ticket`). Output contract:
  - Flag faults: the last line is `tt-feat-NN true|false`, the value flagd serves, read back over OFREP.
  - F3: per service, `F3 <service> command=<command> memory=<limit>`, then one `<pod> restarts=<n> last=<reason>` line per pod. After `on` or `off`, a service that isn't Ready within 300 s prints `<service> not ready after 300s`.
  - F15: `F15 client_max_body_size lines: <n>`.
  - Exit codes: 2 on bad usage, non-zero when flagd serves a value other than the one requested.
- Sourceable functions and settings for tests: `flag_key`, `flip_flag_text`, `limit_body_text`, `f3_command`, `F3_SERVICES`.

- [ ] **Step 1: Write the failing test**

`lab/tests/test_fault_sh.py`:

```python
import json
import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
FAULT_SH = REPO / "lab" / "fault.sh"


def call(function_call, stdin=""):
    return subprocess.run(
        ["bash", "-c", f'source "{FAULT_SH}"; {function_call}'],
        input=stdin, capture_output=True, text=True, check=True,
    ).stdout


def flags_text():
    configmap = yaml.safe_load((REPO / "templates/flagd-config.yaml").read_text())
    return configmap["data"]["flags.yaml"]


def test_script_parses():
    subprocess.run(["bash", "-n", str(FAULT_SH)], check=True)


def test_flag_key_pads_the_number():
    assert call("flag_key F7") == "tt-feat-07"
    assert call("flag_key F22") == "tt-feat-22"


def test_flip_turns_on_only_the_named_flag():
    flags = yaml.safe_load(call("flip_flag_text tt-feat-07 on", flags_text()))["flags"]
    assert [name for name, flag in flags.items() if flag["defaultVariant"] == "on"] == ["tt-feat-07"]


def test_flip_off_restores_the_original():
    on = call("flip_flag_text tt-feat-12 on", flags_text())
    off = call("flip_flag_text tt-feat-12 off", on)
    assert yaml.safe_load(off) == yaml.safe_load(flags_text())


def test_limit_body_adds_one_directive_inside_the_api_location():
    conf = (REPO / "ts-ui-dashboard/nginx.conf").read_text()
    lines = call("limit_body_text", conf).splitlines()
    at = next(i for i, line in enumerate(lines) if "location /api/v1/ {" in line)
    assert lines[at + 1].strip() == "client_max_body_size 300;"
    assert sum("client_max_body_size" in line for line in lines) == 1


def test_f3_command_misconfigures_each_service_heap():
    services = call('echo "$F3_SERVICES"').split()
    assert services == ["ts-train-service", "ts-basic-service", "ts-order-service", "ts-order-other-service"]
    for service in services:
        assert json.loads(call(f"f3_command {service}")) == ["java", "-Xms1g", "-Xmx1g", "-jar", f"/app/{service}-1.0.jar"]


def test_unknown_fault_is_a_usage_error():
    result = subprocess.run(["bash", str(FAULT_SH), "on", "F2"], capture_output=True, text=True)
    assert result.returncode == 2
    assert "usage" in result.stderr
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `uv run --no-project --with pytest==8.3.3 --with pyyaml==6.0.2 --with requests==2.32.3 --with tornado==6.5.10 --with pymysql==1.2.3 pytest lab/tests/test_fault_sh.py -q`

Expected: every test fails because `lab/fault.sh` does not exist.

- [ ] **Step 3: Write `lab/fault.sh`**

```bash
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
```

Run: `chmod +x lab/fault.sh`

- [ ] **Step 4: Run the test and confirm it passes**

Run: `uv run --no-project --with pytest==8.3.3 --with pyyaml==6.0.2 --with requests==2.32.3 --with tornado==6.5.10 --with pymysql==1.2.3 pytest lab/tests/test_fault_sh.py -q`

Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add lab/fault.sh lab/tests/test_fault_sh.py
git diff --staged
git commit -m "feat(lab): fault toggle script for flag, JVM and nginx faults"
```

---

### Task 9: Traffic driver

**Files:**
- Create: `traffic-driver/autoquery/__init__.py`, `queries.py`, `scenarios.py`, `utils.py` (verbatim copies)
- Create: `traffic-driver/autoquery/SOURCE`
- Create: `traffic-driver/driver.py`
- Create: `traffic-driver/Dockerfile`
- Create: `deployment/lab/traffic-driver.yaml`
- Test: `traffic-driver/tests/test_driver.py`, `traffic-driver/tests/test_driver_manifest.py`

**Interfaces:**
- Consumes (auto-query):
  - `Query(url)` with `.session` (a `requests.Session`), `.uid`, `.login()`, `.query_orders(types, query_other)` (returns a list of `(orderId, tripId)` or `None`);
  - `scenarios.query_and_*`.
- Produces:
  - Log lines, one JSON object each: `{"evt":"outcome","method","path","http_status","tt_status","tt_msg","duration_ms"}` and `{"evt":"fare_anomaly","trip","economy","comfort"}`.
  - Image `ghcr.io/rajagopal-epistak/tt-traffic-driver:lab`.
  - Deployment `tt-traffic-driver`.

- [ ] **Step 1: Copy auto-query verbatim and prove it byte for byte**

```bash
mkdir -p traffic-driver/autoquery traffic-driver/tests
for f in __init__.py queries.py scenarios.py utils.py; do
  gh api "repos/FudanSELab/train-ticket-auto-query/contents/$f?ref=9d5bc2d7a1e7dd6f3ef37b85d04a9fec57d322df" \
    -H "Accept: application/vnd.github.raw" > "traffic-driver/autoquery/$f"
done
for f in __init__.py queries.py scenarios.py utils.py; do
  want=$(gh api repos/FudanSELab/train-ticket-auto-query/git/trees/9d5bc2d7a1e7dd6f3ef37b85d04a9fec57d322df --jq ".tree[] | select(.path==\"$f\") | .sha")
  got=$(git hash-object "traffic-driver/autoquery/$f")
  [ "$want" = "$got" ] && echo "$f ok" || echo "$f MISMATCH"
done
```

Expected: four `ok` lines. `__init__.py` is empty upstream.

Write `traffic-driver/autoquery/SOURCE`:

```text
Unmodified copy of __init__.py, queries.py, scenarios.py and utils.py from
https://github.com/FudanSELab/train-ticket-auto-query at 9d5bc2d7a1e7dd6f3ef37b85d04a9fec57d322df.
Used in this lab only; not redistributed.
```

- [ ] **Step 2: Write the failing tests**

`traffic-driver/tests/test_driver.py`:

```python
import datetime
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import driver  # noqa: E402

TRIPS_URL = "http://ts-ui-dashboard:8080/api/v1/travelservice/trips/left"
RESERVED = {"status", "msg", "message", "level", "severity"}


def response(url, status_code=200, body=b"", method="GET", ms=120):
    r = requests.Response()
    r.url = url
    r.status_code = status_code
    r._content = body if isinstance(body, bytes) else json.dumps(body).encode()
    r.elapsed = datetime.timedelta(milliseconds=ms)
    r.request = requests.Request(method, url).prepare()
    return r


def trip(economy, comfort):
    return {"tripId": {"type": "G", "number": "1234"}, "priceForEconomyClass": economy, "priceForConfortClass": comfort}


def test_normalize_path_replaces_ids_and_numbers():
    url = "http://x/api/v1/cancelservice/cancel/5ad7750b-a68b-49c0-a8c0-32776b067703/4d2a46c7-71cb-4cf1-b5bb-b68406d9da6f"
    assert driver.normalize_path(url) == "/api/v1/cancelservice/cancel/{id}/{id}"
    assert driver.normalize_path("http://x/drawback/4d2a46c7-71cb-4cf1-b5bb-b68406d9da6f/50.0") == "/drawback/{id}/{n}"


def test_outcome_reports_business_rejection_behind_http_200():
    body = {"status": 0, "msg": "Order cancel rejected: station locked", "data": None}
    out = driver.outcome(response("http://x/api/v1/cancelservice/cancel/a/b", body=body))
    assert (out["http_status"], out["tt_status"], out["tt_msg"]) == (200, 0, "Order cancel rejected: station locked")
    assert out["evt"] == "outcome" and out["method"] == "GET" and out["duration_ms"] == 120


def test_outcome_survives_non_json_and_list_bodies():
    html = driver.outcome(response("http://x/api/v1/preserveservice/preserve", 413, b"<html>413</html>", "POST"))
    assert (html["http_status"], html["tt_status"], html["tt_msg"]) == (413, None, "")
    listed = driver.outcome(response("http://x/api/v1/foo", body=[1, 2]))
    assert listed["tt_status"] is None


def test_outcome_avoids_datadog_reserved_attributes():
    assert not RESERVED & driver.outcome(response("http://x/y", body={"status": 1})).keys()


def test_fare_anomaly_when_economy_is_not_below_comfort():
    body = {"status": 1, "data": [trip("50.0", "50.0"), trip("19.0", "50.0")]}
    anomalies = driver.price_anomalies(response(TRIPS_URL, body=body, method="POST"))
    assert anomalies == [{"evt": "fare_anomaly", "trip": {"type": "G", "number": "1234"}, "economy": 50.0, "comfort": 50.0}]


def test_fare_check_ignores_blank_prices_other_paths_and_empty_data():
    assert driver.price_anomalies(response(TRIPS_URL, body={"status": 1, "data": [trip("", "50.0"), trip(None, None)]})) == []
    assert driver.price_anomalies(response("http://x/api/v1/orderservice/order/refresh", body={"data": [trip("50.0", "50.0")]})) == []
    assert driver.price_anomalies(response(TRIPS_URL, body={"status": 0, "data": None})) == []
    assert driver.price_anomalies(response(TRIPS_URL, 500, b"oops")) == []


def test_log_response_writes_json_lines(monkeypatch):
    lines = []
    monkeypatch.setattr(driver.outcome_log, "info", lines.append)
    monkeypatch.setattr(driver.outcome_log, "warning", lines.append)
    driver.log_response(response(TRIPS_URL, body={"status": 1, "data": [trip("50.0", "50.0")]}, method="POST"))
    assert [json.loads(line)["evt"] for line in lines] == ["outcome", "fare_anomaly"]


class FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return response(url, body={"status": 1}, method="POST")


class FakeQuery:
    uid = "user-1"

    def __init__(self, pairs=None):
        self.pairs = pairs
        self.session = FakeSession()

    def query_orders(self, types=(0, 1), query_other=False):
        return self.pairs


def test_voucher_scenario_asks_for_a_paid_high_speed_order():
    q = FakeQuery(pairs=[("o1", "G1234")])
    driver.query_and_get_voucher(q)
    method, url, kwargs = q.session.calls[0]
    assert (method, url) == ("POST", driver.VOUCHER_URL)
    assert kwargs["json"] == {"orderId": "o1", "type": 1}
    assert kwargs["timeout"] == driver.VOUCHER_TIMEOUT_SECONDS


def test_voucher_scenario_skips_when_there_are_no_orders():
    q = FakeQuery(pairs=None)
    driver.query_and_get_voucher(q)
    assert q.session.calls == []


def test_weights_include_the_lab_scenarios():
    assert driver.WEIGHTS[driver.query_and_get_voucher] > 0
    assert all(w > 0 for w in driver.WEIGHTS.values())
```

`traffic-driver/tests/test_driver_manifest.py`:

```python
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def test_driver_deployment_runs_the_lab_image_against_the_dashboard():
    doc = yaml.safe_load((REPO / "deployment/lab/traffic-driver.yaml").read_text())
    assert doc["kind"] == "Deployment" and doc["metadata"]["name"] == "tt-traffic-driver"
    assert "namespace" not in doc["metadata"]
    container = doc["spec"]["template"]["spec"]["containers"][0]
    assert container["image"] == "ghcr.io/rajagopal-epistak/tt-traffic-driver:lab"
    assert container["imagePullPolicy"] == "Always"
    env = {e["name"]: e["value"] for e in container["env"]}
    assert env == {
        "TT_URL": "http://ts-ui-dashboard:8080",
        "VOUCHER_URL": "http://ts-voucher-service:16101/getVoucher",
        "INTERVAL_SECONDS": "1",
    }
```

- [ ] **Step 3: Run the tests and confirm they fail**

Run: `uv run --no-project --with pytest==8.3.3 --with pyyaml==6.0.2 --with requests==2.32.3 --with tornado==6.5.10 --with pymysql==1.2.3 pytest traffic-driver -q`

Expected: collection errors, `ModuleNotFoundError: No module named 'driver'`, and a missing-file failure for the manifest.

- [ ] **Step 4: Write `traffic-driver/driver.py`**

```python
import json
import logging
import os
import random
import re
import time
from urllib.parse import urlsplit

from autoquery import scenarios
from autoquery.queries import Query

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("tt-traffic-driver")

# One JSON line per HTTP call so Datadog parses the fields without a pipeline.
# Field names avoid Datadog's reserved attributes (status, msg, message, level).
outcome_log = logging.getLogger("tt-outcome")
outcome_log.propagate = False
_outcome_handler = logging.StreamHandler()
_outcome_handler.setFormatter(logging.Formatter("%(message)s"))
outcome_log.addHandler(_outcome_handler)
outcome_log.setLevel(logging.INFO)

URL = os.environ.get("TT_URL", "http://ts-ui-dashboard:8080")
# The dashboard's nginx only proxies /api/v1/ and the deployed gateway has no /getVoucher route.
VOUCHER_URL = os.environ.get("VOUCHER_URL", "http://ts-voucher-service:16101/getVoucher")
INTERVAL = float(os.environ.get("INTERVAL_SECONDS", "1"))
VOUCHER_TIMEOUT_SECONDS = 15  # a slow voucher lookup must be measured, not abandoned
RELOGIN_SECONDS = 1800  # auth tokens expire after 1 h
HEARTBEAT_EVERY = 50

UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
NUMBER_SEGMENT_RE = re.compile(r"/\d+(\.\d+)?(?=/|$)")


def normalize_path(url):
    path = UUID_RE.sub("{id}", urlsplit(url).path)
    return NUMBER_SEGMENT_RE.sub("/{n}", path)


def _json_body(response):
    try:
        return response.json()
    except ValueError:
        return None


def outcome(response):
    body = _json_body(response)
    is_dict = isinstance(body, dict)
    return {
        "evt": "outcome",
        "method": response.request.method,
        "path": normalize_path(response.url),
        "http_status": response.status_code,
        "tt_status": body.get("status") if is_dict else None,
        "tt_msg": str(body.get("msg") or "")[:200] if is_dict else "",
        "duration_ms": int(response.elapsed.total_seconds() * 1000),
    }


def _price(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# Fare invariant: an economy seat must cost less than a comfort seat on the same trip.
def price_anomalies(response):
    if not urlsplit(response.url).path.endswith("/trips/left"):
        return []
    body = _json_body(response)
    trips = body.get("data") if isinstance(body, dict) else None
    anomalies = []
    for trip in trips if isinstance(trips, list) else []:
        if not isinstance(trip, dict):
            continue
        economy = _price(trip.get("priceForEconomyClass"))
        comfort = _price(trip.get("priceForConfortClass"))
        if economy is not None and comfort is not None and 0 < comfort <= economy:
            anomalies.append({"evt": "fare_anomaly", "trip": trip.get("tripId"), "economy": economy, "comfort": comfort})
    return anomalies


def log_response(response, *args, **kwargs):
    outcome_log.info(json.dumps(outcome(response), separators=(",", ":")))
    for anomaly in price_anomalies(response):
        outcome_log.warning(json.dumps(anomaly, separators=(",", ":")))


# Voucher lookups for paid high-speed orders.
def query_and_get_voucher(q):
    pairs = q.query_orders(types=tuple([1]))
    if not pairs:
        return
    order_id, trip_id = random.choice(pairs)
    q.session.post(VOUCHER_URL, json={"orderId": order_id, "type": 1 if trip_id[:1] in ("G", "D") else 0},
                   timeout=VOUCHER_TIMEOUT_SECONDS)


WEIGHTS = {
    scenarios.query_and_preserve: 4,  # creates the orders the other scenarios act on
    scenarios.query_and_pay: 2,
    scenarios.query_and_collect: 1,
    scenarios.query_and_execute: 1,
    scenarios.query_and_cancel: 1,
    scenarios.query_and_rebook: 1,
    scenarios.query_and_consign: 1,
    query_and_get_voucher: 1,
}


def login():
    while True:
        q = Query(URL)
        q.session.hooks["response"].append(log_response)
        try:
            if q.login():
                return q
        except Exception:
            log.exception("login raised")
        time.sleep(10)


def main():
    q, logged_in_at = login(), time.monotonic()
    runs = errors = 0
    while True:
        scenario = random.choices(list(WEIGHTS), weights=list(WEIGHTS.values()))[0]
        try:
            scenario(q)
        except Exception:
            errors += 1
            log.exception("%s raised", scenario.__name__)
        runs += 1
        if runs % HEARTBEAT_EVERY == 0:
            log.info("heartbeat runs=%d errors=%d", runs, errors)
        if time.monotonic() - logged_in_at > RELOGIN_SECONDS:
            q, logged_in_at = login(), time.monotonic()
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Write `traffic-driver/Dockerfile` and `deployment/lab/traffic-driver.yaml`**

```dockerfile
FROM docker.io/library/python:3.12-slim
RUN pip install --no-cache-dir requests==2.32.3
WORKDIR /opt/driver
COPY autoquery ./autoquery
COPY driver.py .
ENV PYTHONUNBUFFERED=1
CMD ["python", "driver.py"]
```

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: tt-traffic-driver
  labels:
    app: tt-traffic-driver
spec:
  replicas: 1
  selector:
    matchLabels:
      app: tt-traffic-driver
  template:
    metadata:
      labels:
        app: tt-traffic-driver
    spec:
      containers:
        - name: driver
          image: ghcr.io/rajagopal-epistak/tt-traffic-driver:lab
          imagePullPolicy: Always
          env:
            - name: TT_URL
              value: http://ts-ui-dashboard:8080
            - name: VOUCHER_URL
              value: http://ts-voucher-service:16101/getVoucher
            - name: INTERVAL_SECONDS
              value: "1"
          resources:
            requests: {cpu: 100m, memory: 128Mi}
            limits: {cpu: 500m, memory: 256Mi}
```

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `uv run --no-project --with pytest==8.3.3 --with pyyaml==6.0.2 --with requests==2.32.3 --with tornado==6.5.10 --with pymysql==1.2.3 pytest traffic-driver -q`

Expected: `11 passed`.

- [ ] **Step 7: Prove the image builds and imports**

This is a native arm64 build for validation only. CI builds the amd64 image.

Run: `podman build -t localhost/tt-traffic-driver:check traffic-driver && podman run --rm localhost/tt-traffic-driver:check python -c "import driver; print(len(driver.WEIGHTS))" && podman rmi localhost/tt-traffic-driver:check`

Expected: the build succeeds and prints `8`.

- [ ] **Step 8: Commit**

```bash
git add traffic-driver/autoquery/__init__.py traffic-driver/autoquery/queries.py traffic-driver/autoquery/scenarios.py \
        traffic-driver/autoquery/utils.py traffic-driver/autoquery/SOURCE traffic-driver/driver.py traffic-driver/Dockerfile \
        traffic-driver/tests/test_driver.py traffic-driver/tests/test_driver_manifest.py deployment/lab/traffic-driver.yaml
git diff --staged --stat
git commit -m "feat(lab): steady traffic driver with per-call outcome logging"
```

---

### Task 10: CI workflow for lab images

**Files:**
- Create: `.github/workflows/lab-images.yaml`
- Test: `lab/tests/test_workflow.py`

**Interfaces:**
- Produces: on a push to `master` or `lab/**` that touches the listed paths, or on manual dispatch, the workflow pushes:
  - `ghcr.io/rajagopal-epistak/<module>:lab` and `:sha-<commit>` for the five modules;
  - `ghcr.io/rajagopal-epistak/tt-traffic-driver:lab` and `ghcr.io/rajagopal-epistak/ts-voucher-service:lab`, each also tagged `:sha-<commit>`.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
MODULES = ["ts-basic-service", "ts-order-other-service", "ts-inside-payment-service", "ts-payment-service", "ts-cancel-service"]
ACTIONS = {
    "actions/checkout": "v7",
    "actions/setup-java": "v6",
    "docker/setup-buildx-action": "v4",
    "docker/login-action": "v4",
    "docker/build-push-action": "v7",
}


def workflow():
    return yaml.safe_load((REPO / ".github/workflows/lab-images.yaml").read_text())


def steps(job):
    return workflow()["jobs"][job]["steps"]


def test_triggers_and_permissions():
    wf = workflow()
    triggers = wf.get("on", wf.get(True))  # PyYAML reads the bare key `on` as True
    assert "workflow_dispatch" in triggers
    assert triggers["push"]["branches"] == ["master", "lab/**"]
    assert wf["permissions"] == {"contents": "read", "packages": "write"}


def test_service_matrix_is_the_five_changed_modules_and_each_builds_from_its_jar():
    assert workflow()["jobs"]["service"]["strategy"]["matrix"]["module"] == MODULES
    for module in MODULES:
        assert "target/" in (REPO / module / "Dockerfile").read_text(), module


def test_docker_job_builds_the_driver_and_voucher():
    assert workflow()["jobs"]["docker"]["strategy"]["matrix"]["include"] == [
        {"context": "traffic-driver", "image": "tt-traffic-driver"},
        {"context": "ts-voucher-service", "image": "ts-voucher-service"},
    ]


def test_images_are_amd64_and_tagged_lab_and_sha():
    for job in ("service", "docker"):
        push = next(s for s in steps(job) if s.get("uses", "").startswith("docker/build-push-action"))["with"]
        assert push["platforms"] == "linux/amd64"
        assert push["push"] is True
        assert ":lab" in push["tags"] and ":sha-${{ github.sha }}" in push["tags"]


def test_actions_are_pinned_to_current_majors():
    for job in ("service", "docker"):
        for step in steps(job):
            if "uses" in step:
                name, version = step["uses"].split("@")
                assert ACTIONS[name] == version, step["uses"]
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `uv run --no-project --with pytest==8.3.3 --with pyyaml==6.0.2 --with requests==2.32.3 --with tornado==6.5.10 --with pymysql==1.2.3 pytest lab/tests/test_workflow.py -q`

Expected: every test fails because the workflow file is missing.

- [ ] **Step 3: Write `.github/workflows/lab-images.yaml`**

```yaml
name: Lab images

on:
  push:
    branches: [master, "lab/**"]
    paths:
      - "pom.xml"
      - "ts-common/**"
      - "ts-basic-service/**"
      - "ts-order-other-service/**"
      - "ts-inside-payment-service/**"
      - "ts-payment-service/**"
      - "ts-cancel-service/**"
      - "ts-voucher-service/**"
      - "traffic-driver/**"
      - ".github/workflows/lab-images.yaml"
  workflow_dispatch:

permissions:
  contents: read
  packages: write

env:
  REGISTRY: ghcr.io/rajagopal-epistak

jobs:
  service:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        module:
          - ts-basic-service
          - ts-order-other-service
          - ts-inside-payment-service
          - ts-payment-service
          - ts-cancel-service
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-java@v6
        with:
          distribution: temurin
          java-version: "8"
          cache: maven
      - name: Package ${{ matrix.module }}
        run: mvn -B -pl ${{ matrix.module }} -am package -Dmaven.test.skip=true
      - uses: docker/setup-buildx-action@v4
      - uses: docker/login-action@v4
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v7
        with:
          context: ${{ matrix.module }}
          platforms: linux/amd64
          push: true
          tags: |
            ${{ env.REGISTRY }}/${{ matrix.module }}:lab
            ${{ env.REGISTRY }}/${{ matrix.module }}:sha-${{ github.sha }}
          labels: |
            org.opencontainers.image.source=https://github.com/${{ github.repository }}
            org.opencontainers.image.revision=${{ github.sha }}

  docker:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        include:
          - context: traffic-driver
            image: tt-traffic-driver
          - context: ts-voucher-service
            image: ts-voucher-service
    steps:
      - uses: actions/checkout@v7
      - uses: docker/setup-buildx-action@v4
      - uses: docker/login-action@v4
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v7
        with:
          context: ${{ matrix.context }}
          platforms: linux/amd64
          push: true
          tags: |
            ${{ env.REGISTRY }}/${{ matrix.image }}:lab
            ${{ env.REGISTRY }}/${{ matrix.image }}:sha-${{ github.sha }}
          labels: |
            org.opencontainers.image.source=https://github.com/${{ github.repository }}
            org.opencontainers.image.revision=${{ github.sha }}
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `uv run --no-project --with pytest==8.3.3 --with pyyaml==6.0.2 --with requests==2.32.3 --with tornado==6.5.10 --with pymysql==1.2.3 pytest lab/tests/test_workflow.py -q`

Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/lab-images.yaml lab/tests/test_workflow.py
git diff --staged
git commit -m "ci(lab): build the fault services and the driver to GHCR"
```

---

### Task 11: Deployer runbook and lab README

**Files:**
- Create: `lab/DEPLOYER.md`
- Create: `lab/README.md`
- Test: `lab/tests/test_docs.py`

**Interfaces:**
- Consumes:
  - `lab/fault.sh` and its output contract (Task 8);
  - `deployment/lab/flagd.yaml` (Task 7) and `deployment/lab/traffic-driver.yaml` (Task 9);
  - the driver's JSON outcome fields (Task 9).

- [ ] **Step 1: Write the failing test**

```python
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FAULTS = ["F1", "F3", "F7", "F12", "F14", "F15", "F17", "F22"]


def test_every_repo_path_the_deployer_names_exists():
    text = (REPO / "lab/DEPLOYER.md").read_text()
    for path in ["templates/flagd-config.yaml", "deployment/lab/flagd.yaml", "deployment/lab/traffic-driver.yaml", "lab/fault.sh"]:
        assert path in text, path
        assert (REPO / path).exists(), path


def test_docs_and_script_agree_on_the_fault_list():
    script = (REPO / "lab/fault.sh").read_text()
    readme = (REPO / "lab/README.md").read_text()
    deployer = (REPO / "lab/DEPLOYER.md").read_text()
    for fault in FAULTS:
        assert re.search(rf"\b{fault}\b", script), fault
        assert f"| {fault} |" in readme, fault
        assert f"| {fault} |" in deployer, fault


def test_deployer_greps_the_fields_the_driver_writes():
    deployer = (REPO / "lab/DEPLOYER.md").read_text()
    for field in ['"evt":"outcome"', '"http_status"', '"tt_status"', '"duration_ms"', '"evt":"fare_anomaly"']:
        assert field in deployer, field
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `uv run --no-project --with pytest==8.3.3 --with pyyaml==6.0.2 --with requests==2.32.3 --with tornado==6.5.10 --with pymysql==1.2.3 pytest lab/tests/test_docs.py -q`

Expected: every test fails because the files are missing.

- [ ] **Step 3: Write `lab/DEPLOYER.md` with exactly this content**

````markdown
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
````

- [ ] **Step 4: Write `lab/README.md` with exactly this content**

````markdown
# Train-Ticket fault lab

This fork is xlab-uiuc/train-ticket (FudanSELab/train-ticket plus flagd-guarded faults) with eight wiki faults made switchable and a steady traffic driver, for monitoring with Datadog. All faults start off.

| Fault | Switch | What changes when on | Evidence |
|---|---|---|---|
| F1 | `tt-feat-01` | ts-cancel-service reports the refund before running it; the refund lands 8 s later | cancel-service log order |
| F3 | `lab/fault.sh on F3` | train, basic, order and order-other services run a 1g heap inside a 640Mi limit | OOMKilled restarts |
| F7 | `tt-feat-07` | inside-payment pays through ts-payment-service with a 2 s budget; payment answers in 1.5–2.5 s | HTTP 500 on `inside_payment` |
| F12 | `tt-feat-12` | ts-order-other-service rejects cancels of K/Z/T-series orders touching Shanghai or Nanjing | `tt_status` 0, "station locked" |
| F14 | `tt-feat-14` | ts-basic-service prices economy seats at distance × 1 | `fare_anomaly` lines |
| F15 | `lab/fault.sh on F15` | the dashboard's nginx refuses API bodies over 300 bytes (bookings with food or consign) | HTTP 413 |
| F17 | `tt-feat-17` | ts-voucher-service sleeps 10 s in MySQL per lookup (from xlab) | `/getVoucher` ≥ 10 s |
| F22 | `tt-feat-22` | ts-voucher-service's lookup names a missing column, so Print Voucher shows "Empty. No data!" | HTTP 500 on `/getVoucher` |

Switch any fault with `lab/fault.sh on|off|status <F>` (kubectl pointed at the lab cluster; namespace `train-ticket`, override with `NAMESPACE`).

- Deploy: `lab/DEPLOYER.md` is an agent-executable runbook.
- Images: `.github/workflows/lab-images.yaml` builds the six changed services and the driver to `ghcr.io/rajagopal-epistak/*:lab` on push. New packages start private; make each one public once under the package's settings on GitHub.
- Build and test locally: `hack/lab/mvn.sh <module> test`, and `uv run --no-project --with pytest==8.3.3 --with pyyaml==6.0.2 --with requests==2.32.3 --with tornado==6.5.10 --with pymysql==1.2.3 pytest lab traffic-driver ts-voucher-service/tests -q`.
- `traffic-driver/autoquery/` is an unmodified copy of FudanSELab/train-ticket-auto-query at `9d5bc2d`.
````

- [ ] **Step 5: Run the test and confirm it passes**

Run: `uv run --no-project --with pytest==8.3.3 --with pyyaml==6.0.2 --with requests==2.32.3 --with tornado==6.5.10 --with pymysql==1.2.3 pytest lab/tests/test_docs.py -q`

Expected: `3 passed`.

- [ ] **Step 6: Commit**

```bash
git add lab/DEPLOYER.md lab/README.md lab/tests/test_docs.py
git diff --staged --stat
git commit -m "docs(lab): deployer runbook with fault smoke gates and lab README"
```

---

### Task 12: Whole-branch verification sweep

**Files:** none are created. A report goes outside the repo.

- [ ] **Step 1: Run every new Java test, one module at a time**

```bash
hack/lab/mvn.sh ts-basic-service test -Dtest='BasicServiceImplF14Test,FeatureFlagServiceTest' -Dsurefire.failIfNoSpecifiedTests=false 2>&1 | grep -E "Tests run:|BUILD"
hack/lab/mvn.sh ts-order-other-service test -Dtest='OrderOtherServiceImplF12Test,FeatureFlagServiceTest' -Dsurefire.failIfNoSpecifiedTests=false 2>&1 | grep -E "Tests run:|BUILD"
hack/lab/mvn.sh ts-payment-service test -Dtest='PaymentServiceImplF7Test,FeatureFlagServiceTest' -Dsurefire.failIfNoSpecifiedTests=false 2>&1 | grep -E "Tests run:|BUILD"
hack/lab/mvn.sh ts-inside-payment-service test -Dtest=InsidePaymentServiceImplF7Test -Dsurefire.failIfNoSpecifiedTests=false 2>&1 | grep -E "Tests run:|BUILD"
hack/lab/mvn.sh ts-cancel-service test -Dtest=CancelServiceImplF1Test -Dsurefire.failIfNoSpecifiedTests=false 2>&1 | grep -E "Tests run:|BUILD"
```

Expected totals: 4, 10, 4, 4 and 2 tests, all with `Failures: 0, Errors: 0`, and five `BUILD SUCCESS` lines.

- [ ] **Step 2: Package every module the way CI does**

```bash
for m in ts-basic-service ts-order-other-service ts-inside-payment-service ts-payment-service ts-cancel-service; do
  echo "== $m"; hack/lab/mvn.sh "$m" package -Dmaven.test.skip=true 2>&1 | grep -E "BUILD|ERROR"
done
```

Expected: five `BUILD SUCCESS` lines.

- [ ] **Step 3: Run the Python suite and the script syntax check**

Run: `uv run --no-project --with pytest==8.3.3 --with pyyaml==6.0.2 --with requests==2.32.3 --with tornado==6.5.10 --with pymysql==1.2.3 pytest lab traffic-driver ts-voucher-service/tests -q && bash -n lab/fault.sh hack/lab/mvn.sh && echo syntax-ok`

Expected: `35 passed` and `syntax-ok`.

- [ ] **Step 4: Check the branch touched only the planned files**

Run: `git status --short && git log --oneline c9537c15..HEAD && git diff --name-only c9537c15..HEAD | sort`

Expected:
- `git status` prints nothing.
- There are 12 task commits, plus one commit per review fix round.
- The file list is exactly:

```text
.github/workflows/lab-images.yaml
CLAUDE.md
deployment/kubernetes-manifests/quickstart-k8s/yamls/deploy.yaml.sample
deployment/lab/flagd.yaml
deployment/lab/traffic-driver.yaml
docs/superpowers/plans/2026-09-25-easy-faults-and-traffic.md
hack/lab/mvn.sh
lab/DEPLOYER.md
lab/README.md
lab/fault.sh
lab/tests/test_docs.py
lab/tests/test_fault_sh.py
lab/tests/test_manifests.py
lab/tests/test_workflow.py
traffic-driver/Dockerfile
traffic-driver/autoquery/SOURCE
traffic-driver/autoquery/__init__.py
traffic-driver/autoquery/queries.py
traffic-driver/autoquery/scenarios.py
traffic-driver/autoquery/utils.py
traffic-driver/driver.py
traffic-driver/tests/test_driver.py
traffic-driver/tests/test_driver_manifest.py
ts-basic-service/src/main/java/fdse/microservice/BasicApplication.java
ts-basic-service/src/main/java/fdse/microservice/service/BasicServiceImpl.java
ts-basic-service/src/main/java/fdse/microservice/service/FeatureFlagService.java
ts-basic-service/src/test/java/fdse/microservice/service/BasicServiceImplF14Test.java
ts-basic-service/src/test/java/fdse/microservice/service/FeatureFlagServiceTest.java
ts-cancel-service/src/main/java/cancel/service/CancelServiceImpl.java
ts-cancel-service/src/test/java/cancel/service/CancelServiceImplF1Test.java
ts-inside-payment-service/src/main/java/inside_payment/InsidePaymentApplication.java
ts-inside-payment-service/src/main/java/inside_payment/service/InsidePaymentServiceImpl.java
ts-inside-payment-service/src/test/java/inside_payment/service/InsidePaymentServiceImplF7Test.java
ts-order-other-service/src/main/java/other/OrderOtherApplication.java
ts-order-other-service/src/main/java/other/service/FeatureFlagService.java
ts-order-other-service/src/main/java/other/service/OrderOtherServiceImpl.java
ts-order-other-service/src/test/java/other/service/FeatureFlagServiceTest.java
ts-order-other-service/src/test/java/other/service/OrderOtherServiceImplF12Test.java
ts-payment-service/src/main/java/com/trainticket/PaymentApplication.java
ts-payment-service/src/main/java/com/trainticket/service/FeatureFlagService.java
ts-payment-service/src/main/java/com/trainticket/service/PaymentServiceImpl.java
ts-payment-service/src/test/java/com/trainticket/service/FeatureFlagServiceTest.java
ts-payment-service/src/test/java/com/trainticket/service/PaymentServiceImplF7Test.java
ts-voucher-service/server.py
ts-voucher-service/tests/test_f22.py
```

- [ ] **Step 5: Write the build report and stop**

Write `/private/tmp/claude-501/-Users-barath-Documents-barath-work-train-ticket-test-lab/0ba2deb1-8c19-4f26-a79f-da3bf7077329/scratchpad/tt-build-report.md` with:
- the Step 1–4 outputs;
- every deviation from this plan, with the reason;
- the pre-existing issues you noticed (dead `AsyncTask`, duplicate imports in `InsidePaymentApplication`, auto-query's `random_str()`/`random_phone()` returning `None`, anything else).

Do not push. Return three lines: `DONE` or `STOPPED at Task N Step M`, the last commit SHA, and the report path.
