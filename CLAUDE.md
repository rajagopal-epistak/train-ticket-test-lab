# Train-Ticket fault lab

Fork of FudanSELab/train-ticket, fast-forwarded onto xlab-uiuc/train-ticket (flagd-guarded faults). Lab additions live in `lab/`, `hack/lab/`, `deployment/lab/`, `traffic-driver/` and `.github/workflows/lab-images.yaml`; `lab/README.md` lists the faults.

- Runs on a real host (macOS arm64). Containers: podman only, never Docker Desktop. Never mount the home directory into a VM.
- The host's only JDK is mise's Temurin 21, and it exists only to run jdtls. There is no Maven, kubectl or helm on the host. Build and test Java only through `hack/lab/mvn.sh <module> <maven args>`.
- Java: navigate with the LSP (jdtls), and check its diagnostics after every edit. Start Claude Code at the repo root so jdtls imports the Maven project. jdtls must run with the Lombok javaagent; without it every Lombok accessor reads as undefined.
- Python tests: `uv run --no-project --with pytest==8.3.3 --with pyyaml==6.0.2 --with requests==2.32.3 --with tornado==6.5.10 --with pymysql==1.2.3 pytest lab traffic-driver ts-voucher-service/tests -q`.
- The existing JUnit 4 tests under `ts-*/src/test` never run (Spring Boot 2.7 starter-test has no vintage engine). Write new tests in JUnit 5.
- Faults: flag-driven ones read flagd at `flagd:8013` (ConfigMap `flagd-config`, namespace `train-ticket`) and default to off. With every flag off the services must behave exactly as upstream/xlab.
- Never push, merge or amend without the owner's explicit confirmation. Stage files by name. No trailers and no AI/Claude mentions in commits.
