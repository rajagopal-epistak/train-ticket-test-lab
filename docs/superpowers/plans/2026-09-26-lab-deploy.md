# Lab Deploy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (or superpowers:subagent-driven-development) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One script, `lab/lab.sh up|test|down`, that an agent runs to deploy the Train-Ticket lab with Datadog monitoring on any x86_64 cluster, prove F22 is detected, and tear everything down.

**Architecture:**
- Terraform in two stages:
  - `lab/terraform/datadog`: the Datadog Operator and a DatadogAgent. It ships as a local Helm chart, so the CRD and the custom resource apply in one run.
  - `lab/terraform/lab`: the namespace, the four infrastructure charts, the 117 Train-Ticket objects decoded from the committed YAML, flagd, the traffic driver and twelve fault-agnostic monitors.
- A bash wrapper that does four things:
  - runs the preflight checks;
  - decides whether to install the Agent;
  - sequences the stages and the live gates;
  - drives the F22 round trip through the existing `lab/fault.sh`.
- `down` runs the repo's native `make reset-deploy` before Terraform destroys the rest.

**Tech Stack:**
- Terraform ≥ 1.8 (1.16.4 tested), with the providers hashicorp/helm 3.3.0, hashicorp/kubernetes 3.2.1 and DataDog/datadog 4.22.0;
- Datadog Operator chart 2.27.0 with Agent 7.83.3;
- bash, kubectl, helm, python3;
- pytest with stubbed CLIs.

**Spec:** `docs/superpowers/specs/2026-09-26-lab-deploy-design.md`. The spec's "Refinements from the dry-run" section overrides earlier wording where they differ.

**Provenance:** every file below was written and tested in a scratch clone before this plan was written: 81 tests passed, shellcheck was clean, and `terraform validate` passed for both stages. The code blocks are that tested content, byte for byte. Write each file exactly as given.

## Orchestration shape

- **Build:** one dev agent (general-purpose, Sonnet, xhigh effort inherited from settings) runs Tasks 0–5 with superpowers:executing-plans; the session that owns this plan reviews its work before the deep review. The code is final and tested, so the build is a transcription plus a test run per task. Estimate: about 150–250k tokens.
- **Review:** one deep reviewer, Sonnet at xhigh effort, over the whole `master..lab/deploy` diff with the spec. Estimate: 300–400k tokens. A fix round follows only for confirmed findings, re-reviewed by a fresh, cheap, diff-scoped agent.
- **Token ceiling:** set by the owner before the build.

## Global Constraints

- **Repo and branch:**
  - Work in the worktree `/Users/barath/Documents/barath/work/train-ticket-test-lab-deploy`, on branch `lab/deploy` (from `master` `a4c1abce`).
  - Never push, merge, amend or rebase.
  - Never touch the main checkout `/Users/barath/Documents/barath/work/train-ticket-test-lab`.
- **The host is a real macOS arm64 machine:**
  - No cluster is contacted and nothing is deployed in this build.
  - Run tools only through `mise exec <tool>@<version> -- …`: `terraform@1.16.4`, `helm@3.22.0`, `shellcheck@0.11.0`. Never edit `~/.config/mise/config.toml`.
- **Python tests:** `mise exec terraform@1.16.4 helm@3.22.0 -- uv run --no-project --with pytest==8.3.3 --with pyyaml==6.0.2 --with requests==2.32.3 --with tornado==6.5.10 --with pymysql==1.2.3 pytest <paths> -q`, from the worktree root.
- **Touch only the files each task lists.** `lab/fault.sh`, `deployment/`, `templates/`, `hack/` and the Makefile stay unchanged. The deploy reuses them.
- **Keys never appear in:**
  - command lines: curl reads its headers from stdin via `-K -`, and the Secret is built from `--from-env-file=<(printf …)`;
  - files;
  - Terraform state: the Secret is made by `lab.sh`, and the Datadog provider reads `DD_API_KEY`/`DD_APP_KEY` from the environment.
- **Commits:**
  - one per task, conventional type with scope `lab`;
  - run `git diff --staged` before each;
  - stage files by name;
  - no trailer of any kind, and no mention of Claude or AI.

## Review Focus

1. **Re-running `up` over an active fault** restores the baseline. That covers F3's JVM `command`, F15's nginx mount and any flag left on (S2). Pinned by `test_faults_on_reads_flags_and_patches` and `test_faults_off_switches_off_only_what_is_on` (Task 3).
2. **A cluster that already has a Datadog Agent,** whether a DaemonSet found by label or image, or a package on a node's OS, gets no second Agent. A cluster-agent image alone does not count as an Agent. Pinned by `test_agent_decision`, 5 cases (Task 3).
3. **A failed or interrupted `test`** never leaves F22 on. Pinned by `test_f22_not_detected_fails_and_still_switches_the_fault_off` (Task 3), and the EXIT trap covers interrupts.
4. **Datadog keys** never reach argv or files. Pinned by `test_datadog_keys_travel_on_stdin_never_argv` and `test_agent_secret_keys_never_reach_argv` (Task 3).
5. **Other people's things survive:**
   - a `train-ticket` namespace from another lab or a manual deploy;
   - a `datadog` namespace that isn't this lab's;
   - a `deploy.yaml` from an earlier `make deploy`;
   - a typo in `lab/telemetry.yaml` (refused before any apply).

   Pinned by `test_namespace_guard`, `test_agent_install_refuses_a_datadog_namespace_owned_by_someone_else`, `test_down_keeps_a_deploy_yaml_it_did_not_generate` and `test_telemetry_names_must_be_known` (Task 3), plus `test_unknown_names_are_reported` (Task 2).

---

### Task 0: Start state and plan commit

**Files:**
- Add: `docs/superpowers/plans/2026-09-26-lab-deploy.md` (this plan, already on disk)

- [ ] **Step 1: Confirm the starting state**

Run: `cd /Users/barath/Documents/barath/work/train-ticket-test-lab-deploy && git branch --show-current && git log --oneline -1 && git status --short`

Expected: `lab/deploy`, then `12e9bd14 docs(lab): record the deploy design refinements found in the dry-run`, then only `?? docs/superpowers/plans/`. If anything differs, stop and report.

- [ ] **Step 2: Confirm the tools**

Run: `mise exec terraform@1.16.4 helm@3.22.0 shellcheck@0.11.0 -- sh -c 'terraform version | head -1; helm version --short; shellcheck --version | sed -n 2p'`

Expected: `Terraform v1.16.4`, `v3.22.0+…`, `version: 0.11.0`.

- [ ] **Step 3: Commit the plan**

```bash
git add docs/superpowers/plans/2026-09-26-lab-deploy.md
git diff --staged --stat
git commit -m "docs(lab): implementation plan for the Terraform lab deploy"
```

---

### Task 1: Terraform stage `datadog` (Operator + DatadogAgent chart)

**Files:**
- Create: `lab/terraform/.gitignore`, `lab/terraform/datadog/versions.tf`, `variables.tf`, `main.tf`
- Create: `lab/terraform/datadog/agent-chart/Chart.yaml`, `values.yaml`, `templates/datadogagent.yaml`
- Create (generated): `lab/terraform/datadog/.terraform.lock.hcl`
- Test: `lab/tests/test_terraform_datadog.py`

**Interfaces:**
- Produces:
  - stage `datadog` with variables `kubeconfig`, `lab_name`, `dd_site`, `apm_enabled` (Task 3 exports them as `TF_VAR_*`);
  - `helm_release.operator` and `helm_release.agent`, in namespace `datadog`;
  - the DatadogAgent `datadog`. The Operator names its objects `datadog-cluster-agent` (Deployment) and `datadog-agent` (DaemonSet), and Task 3's G1 waits for them;
  - the Secret `datadog-secret` (`api-key`, `app-key`) is expected to exist already; Task 3 creates it.

- [ ] **Step 1: Write the failing test**

`lab/tests/test_terraform_datadog.py`:

```python
import os
import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
STAGE = REPO / "lab" / "terraform" / "datadog"
VARS = {"TF_VAR_kubeconfig": "/nonexistent", "TF_VAR_lab_name": "tt-lab-1", "TF_VAR_dd_site": "datadoghq.eu",
        "TF_VAR_apm_enabled": "true"}


def terraform(*args):
    return subprocess.run(["terraform", f"-chdir={STAGE}", *args], capture_output=True, text=True,
                          env={**os.environ, **VARS})


def helm_template(*args):
    return subprocess.run(["helm", "template", *args], capture_output=True, text=True)


def test_formatted_and_valid():
    assert terraform("init", "-backend=false", "-input=false").returncode == 0
    assert terraform("fmt", "-check", "-recursive").returncode == 0
    r = terraform("validate")
    assert r.returncode == 0, r.stderr


def test_agent_chart_renders_the_documented_fields():
    r = helm_template("datadog-agent", str(STAGE / "agent-chart"), "-n", "datadog",
                      "--set", "labName=tt-lab-1", "--set", "site=datadoghq.eu", "--set", "apmEnabled=false")
    assert r.returncode == 0, r.stderr
    agent = yaml.safe_load(r.stdout)
    spec = agent["spec"]
    assert agent["apiVersion"] == "datadoghq.com/v2alpha1" and agent["metadata"]["namespace"] == "datadog"
    assert spec["global"]["clusterName"] == "tt-lab-1" and spec["global"]["site"] == "datadoghq.eu"
    assert spec["global"]["credentials"]["apiSecret"] == {"secretName": "datadog-secret", "keyName": "api-key"}
    assert spec["features"]["apm"]["enabled"] is False
    assert spec["features"]["apm"]["instrumentation"]["enabled"] is False
    target = spec["features"]["apm"]["instrumentation"]["targets"][0]
    assert target["namespaceSelector"]["matchNames"] == ["train-ticket"]
    assert target["ddTraceVersions"] == {"java": "1", "python": "4"}
    assert {"name": "DD_ENV", "value": "tt-lab-1"} in target["ddTraceConfigs"]
    assert {"name": "DD_SERVICE", "valueFrom": {"fieldRef": {"fieldPath": "metadata.labels['app']"}}} in target["ddTraceConfigs"]
    env = {e["name"]: e["value"] for e in spec["override"]["nodeAgent"]["env"]}
    assert env == {"DD_CONTAINER_EXCLUDE_LOGS": "kube_namespace:.*", "DD_CONTAINER_INCLUDE_LOGS": "kube_namespace:train-ticket"}
    assert spec["override"]["nodeAgent"]["image"]["tag"] == spec["override"]["clusterAgent"]["image"]["tag"] == "7.83.3"


def test_agent_chart_requires_a_lab_name():
    r = helm_template("x", str(STAGE / "agent-chart"))
    assert r.returncode != 0 and "labName is required" in r.stderr
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `mise exec terraform@1.16.4 helm@3.22.0 -- uv run --no-project --with pytest==8.3.3 --with pyyaml==6.0.2 --with requests==2.32.3 --with tornado==6.5.10 --with pymysql==1.2.3 pytest lab/tests/test_terraform_datadog.py -q`

Expected: 3 failed; the stage directory and the chart don't exist yet.

- [ ] **Step 3: Write the stage**

`lab/terraform/.gitignore`:

```
.terraform/
*.tfstate
*.tfstate.*
terraform.tfstate.d/
```

`lab/terraform/datadog/versions.tf`:

```hcl
terraform {
  required_version = ">= 1.8.0"
  required_providers {
    helm = {
      source  = "hashicorp/helm"
      version = "~> 3.3"
    }
  }
}

provider "helm" {
  kubernetes = {
    config_path = var.kubeconfig
  }
}
```

`lab/terraform/datadog/variables.tf`:

```hcl
variable "kubeconfig" {
  description = "Minified kubeconfig for the lab context, written by lab/lab.sh."
  type        = string
}

variable "lab_name" {
  description = "Datadog cluster name and env tag for this lab."
  type        = string
}

variable "dd_site" {
  description = "Datadog site, e.g. datadoghq.eu."
  type        = string
}

variable "apm_enabled" {
  description = "Single Step Instrumentation for namespace train-ticket."
  type        = bool
}
```

`lab/terraform/datadog/main.tf`:

```hcl
# Stage 1: the Datadog Operator, then the DatadogAgent it reconciles.
# The DatadogAgent ships as a local chart because a kubernetes_manifest needs its CRD at plan time;
# a helm_release only needs it at apply time, after the Operator release has installed it.
# Namespace `datadog` and Secret `datadog-secret` are created by lab/lab.sh, so the API keys never enter Terraform state.

resource "helm_release" "operator" {
  name       = "datadog-operator"
  repository = "https://helm.datadoghq.com"
  chart      = "datadog-operator"
  version    = "2.27.0"
  namespace  = "datadog"
  wait       = true
  timeout    = 600
}

resource "helm_release" "agent" {
  name      = "datadog-agent"
  chart     = "${path.module}/agent-chart"
  namespace = "datadog"
  wait      = true
  timeout   = 600
  values = [yamlencode({
    labName    = var.lab_name
    site       = var.dd_site
    apmEnabled = var.apm_enabled
  })]
  depends_on = [helm_release.operator]
}
```

`lab/terraform/datadog/agent-chart/Chart.yaml`:

```yaml
apiVersion: v2
name: tt-lab-datadog-agent
description: The DatadogAgent resource for the Train-Ticket lab.
type: application
version: 0.1.0
```

`lab/terraform/datadog/agent-chart/values.yaml`:

```yaml
labName: ""
site: datadoghq.com
apmEnabled: true
agentVersion: "7.83.3"
```

`lab/terraform/datadog/agent-chart/templates/datadogagent.yaml`:

```yaml
apiVersion: datadoghq.com/v2alpha1
kind: DatadogAgent
metadata:
  name: datadog
  namespace: {{ .Release.Namespace }}
spec:
  global:
    clusterName: {{ required "labName is required" .Values.labName | quote }}
    site: {{ .Values.site | quote }}
    tags:
      - {{ printf "env:%s" .Values.labName | quote }}
      - {{ printf "lab:%s" .Values.labName | quote }}
    credentials:
      apiSecret:
        secretName: datadog-secret
        keyName: api-key
      appSecret:
        secretName: datadog-secret
        keyName: app-key
  features:
    apm:
      enabled: {{ .Values.apmEnabled }}
      instrumentation:
        enabled: {{ .Values.apmEnabled }}
        targets:
          - name: train-ticket
            namespaceSelector:
              matchNames: ["train-ticket"]
            ddTraceVersions:
              java: "1"
              python: "4"
            ddTraceConfigs:
              - name: DD_SERVICE
                valueFrom:
                  fieldRef:
                    fieldPath: metadata.labels['app']
              - name: DD_ENV
                value: {{ .Values.labName | quote }}
              # Tornado is off by default in ddtrace ("Automatic: no"); inferred switch, measured on the first run.
              - name: DD_TRACE_TORNADO_ENABLED
                value: "true"
    logCollection:
      enabled: true
      containerCollectAll: true
    kubeStateMetricsCore:
      enabled: true
  override:
    nodeAgent:
      image:
        tag: {{ .Values.agentVersion | quote }}
      env:
        - name: DD_CONTAINER_EXCLUDE_LOGS
          value: "kube_namespace:.*"
        - name: DD_CONTAINER_INCLUDE_LOGS
          value: "kube_namespace:train-ticket"
    clusterAgent:
      image:
        tag: {{ .Values.agentVersion | quote }}
```

- [ ] **Step 4: Lock the provider for the runner platforms**

Run: `mise exec terraform@1.16.4 -- terraform -chdir=lab/terraform/datadog init -backend=false -input=false >/dev/null && mise exec terraform@1.16.4 -- terraform -chdir=lab/terraform/datadog providers lock -platform=linux_amd64 -platform=linux_arm64 -platform=darwin_amd64 -platform=darwin_arm64 && grep -A1 '^provider' lab/terraform/datadog/.terraform.lock.hcl`

Expected: `provider "registry.terraform.io/hashicorp/helm"`, then `version     = "3.3.0"`.

- [ ] **Step 5: Run the test and confirm it passes**

Run: `mise exec terraform@1.16.4 helm@3.22.0 -- uv run --no-project --with pytest==8.3.3 --with pyyaml==6.0.2 --with requests==2.32.3 --with tornado==6.5.10 --with pymysql==1.2.3 pytest lab/tests/test_terraform_datadog.py -q`

Expected: `3 passed`. `git status --short` shows no `.terraform/` directory, because it is ignored.

- [ ] **Step 6: Commit**

```bash
git add lab/terraform/.gitignore lab/terraform/datadog/versions.tf lab/terraform/datadog/variables.tf lab/terraform/datadog/main.tf \
        lab/terraform/datadog/.terraform.lock.hcl lab/terraform/datadog/agent-chart/Chart.yaml \
        lab/terraform/datadog/agent-chart/values.yaml lab/terraform/datadog/agent-chart/templates/datadogagent.yaml \
        lab/tests/test_terraform_datadog.py
git diff --staged --stat
git commit -m "feat(lab): Terraform stage for the Datadog Operator and Agent"
```

---

### Task 2: Terraform stage `lab` (Train-Ticket, flagd, driver, monitors, switches)

**Files:**
- Create: `lab/terraform/lab/versions.tf`, `variables.tf`, `infra.tf`, `app.tf`, `monitors.tf`, `outputs.tf`
- Create: `lab/telemetry.yaml`
- Create (generated): `lab/terraform/lab/.terraform.lock.hcl`
- Test: `lab/tests/test_terraform_lab.py`

**Interfaces:**
- Consumes these repo files, unchanged:
  - `deployment/kubernetes-manifests/quickstart-k8s/charts/{mysql,nacos,rabbitmq}`;
  - `yamls/{secret.yaml,svc.yaml,deploy.yaml.sample}`;
  - `deployment/lab/flagd.yaml`, `deployment/lab/traffic-driver.yaml`, `templates/flagd-config.yaml`.
- Produces:
  - variables `kubeconfig`, `lab_name`, `dd_site`, `apm_enabled`, `apm_hosts_budget`, `apm_ingest_gb_budget`, `telemetry_file`;
  - locals `deployments` (48), `others` (73), `logs_off`, `apm_off`, `unknown_services`, `monitors`;
  - output `monitor_ids`: a map of monitor key to id, with keys `java_latency`, `voucher_latency`, `java_errors`, `voucher_errors`, `oom_killed`, `restarts`, `edge_5xx`, `edge_4xx`, `business_rejections`, `fare_anomaly`, `apm_hosts_budget`, `apm_ingest_budget`. Task 3 reads `edge_5xx` and `voucher_errors`.

- [ ] **Step 1: Write the failing test**

`lab/tests/test_terraform_lab.py`:

```python
import json
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
STAGE = REPO / "lab" / "terraform" / "lab"
VARS = {
    "TF_VAR_kubeconfig": "/nonexistent", "TF_VAR_lab_name": "tt-lab-1", "TF_VAR_dd_site": "datadoghq.eu",
    "TF_VAR_apm_enabled": "true", "TF_VAR_apm_hosts_budget": "4", "TF_VAR_apm_ingest_gb_budget": "150",
    "TF_VAR_telemetry_file": str(REPO / "lab" / "telemetry.yaml"),
}


def terraform(*args, env=None, stdin=""):
    return subprocess.run(["terraform", f"-chdir={STAGE}", *args], input=stdin, capture_output=True, text=True,
                          env={**os.environ, **VARS, **(env or {})})


@pytest.fixture(scope="module", autouse=True)
def init():
    r = terraform("init", "-backend=false", "-input=false")
    assert r.returncode == 0, r.stderr


def evaluate(expr, **env):
    r = terraform("console", env=env, stdin=f"jsonencode({expr})\n")
    assert r.returncode == 0, r.stderr
    return json.loads(json.loads(r.stdout))


def test_formatted_and_valid():
    assert terraform("fmt", "-check", "-recursive").returncode == 0
    r = terraform("validate")
    assert r.returncode == 0, r.stderr


def test_every_object_make_deploy_applies_plus_flagd_and_driver():
    assert evaluate("length(local.deployments)") == 46 + 2
    assert evaluate("length(local.others)") == 27 + 44 + 2  # secrets, services, flagd Service and ConfigMap
    assert evaluate('local.deployments["ts-voucher-service"].metadata.namespace') == "train-ticket"
    assert evaluate('local.others["ConfigMap/flagd-config"].metadata.namespace') == "train-ticket"


def test_committed_telemetry_switches_nothing_off():
    assert evaluate("local.unknown_services") == []
    for name in ("ts-news-service", "tt-traffic-driver", "flagd"):
        meta = evaluate(f'local.deployments["{name}"].spec.template.metadata')
        assert "annotations" not in meta and "admission.datadoghq.com/enabled" not in meta["labels"]


def test_switches_land_on_exactly_the_listed_deployments(tmp_path):
    f = tmp_path / "telemetry.yaml"
    f.write_text("logs_off: [ts-news-service]\napm_off:\n  - tt-traffic-driver\n")
    env = {"TF_VAR_telemetry_file": str(f)}
    assert evaluate('local.deployments["ts-news-service"].spec.template.metadata.annotations', **env) == {
        "ad.datadoghq.com/logs_exclude": "true"}
    assert evaluate('local.deployments["tt-traffic-driver"].spec.template.metadata.labels', **env) == {
        "app": "tt-traffic-driver", "admission.datadoghq.com/enabled": "false"}
    assert evaluate('local.deployments["ts-basic-service"].spec.template.metadata', **env) == {
        "labels": {"app": "ts-basic-service"}}


def test_unknown_names_are_reported(tmp_path):
    f = tmp_path / "telemetry.yaml"
    f.write_text("logs_off: [ts-bogus]\napm_off: []\n")
    assert evaluate("local.unknown_services", TF_VAR_telemetry_file=str(f)) == ["ts-bogus"]


def test_apm_switch_drops_only_the_apm_monitors():
    on = set(evaluate("keys(local.monitors)"))
    off = set(evaluate("keys(local.monitors)", TF_VAR_apm_enabled="false"))
    assert on - off == {"java_latency", "voucher_latency", "java_errors", "voucher_errors"}
    assert off == {"edge_5xx", "edge_4xx", "business_rejections", "fare_anomaly", "oom_killed", "restarts",
                   "apm_hosts_budget", "apm_ingest_budget"}


def test_log_monitors_scope_the_driver_and_budget_is_a_daily_share():
    monitors = evaluate("local.monitors")
    assert "service:tt-traffic-driver" in monitors["edge_5xx"]["expr"]
    assert '.by("@path")' in monitors["edge_5xx"]["expr"]
    assert monitors["apm_ingest_budget"]["critical"] == 5_000_000_000
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `mise exec terraform@1.16.4 helm@3.22.0 -- uv run --no-project --with pytest==8.3.3 --with pyyaml==6.0.2 --with requests==2.32.3 --with tornado==6.5.10 --with pymysql==1.2.3 pytest lab/tests/test_terraform_lab.py -q`

Expected: errors at the module fixture: `init` fails because `lab/terraform/lab` does not exist.

- [ ] **Step 3: Write the stage and the switches file**

`lab/terraform/lab/versions.tf`:

```hcl
terraform {
  required_version = ">= 1.8.0"
  required_providers {
    helm = {
      source  = "hashicorp/helm"
      version = "~> 3.3"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 3.2"
    }
    datadog = {
      source  = "DataDog/datadog"
      version = "~> 4.22"
    }
  }
}

provider "kubernetes" {
  config_path = var.kubeconfig
}

provider "helm" {
  kubernetes = {
    config_path = var.kubeconfig
  }
}

# api_key and app_key come from DD_API_KEY / DD_APP_KEY in the environment.
provider "datadog" {
  api_url = "https://api.${var.dd_site}/"
}
```

`lab/terraform/lab/variables.tf`:

```hcl
variable "kubeconfig" {
  description = "Minified kubeconfig for the lab context, written by lab/lab.sh."
  type        = string
}

variable "lab_name" {
  description = "Datadog cluster name, env tag and monitor-name prefix for this lab."
  type        = string
}

variable "dd_site" {
  description = "Datadog site, e.g. datadoghq.eu."
  type        = string
}

variable "apm_enabled" {
  description = "Create the APM monitors."
  type        = bool
}

variable "apm_hosts_budget" {
  description = "Alert when estimated APM hosts exceed this."
  type        = number
}

variable "apm_ingest_gb_budget" {
  description = "Monthly ingested-span budget in GB; the monitor alerts on a daily share."
  type        = number
}

variable "telemetry_file" {
  description = "Per-service logs_off / apm_off switches."
  type        = string
}
```

`lab/terraform/lab/infra.tf`:

```hcl
# Namespace and the four infrastructure charts, with the values `make deploy` uses (hack/deploy/utils.sh).

locals {
  repo   = abspath("${path.module}/../../..")
  charts = "${local.repo}/deployment/kubernetes-manifests/quickstart-k8s/charts"
}

resource "kubernetes_namespace_v1" "train_ticket" {
  metadata {
    name   = "train-ticket"
    labels = { lab = var.lab_name }
  }
}

resource "helm_release" "nacosdb" {
  name      = "nacosdb"
  chart     = "${local.charts}/mysql"
  namespace = kubernetes_namespace_v1.train_ticket.metadata[0].name
  timeout   = 900
  set = [
    { name = "mysql.mysqlUser", value = "nacos" },
    { name = "mysql.mysqlPassword", value = "Abcd1234#" },
    { name = "mysql.mysqlDatabase", value = "nacos" },
  ]
}

resource "helm_release" "nacos" {
  name      = "nacos"
  chart     = "${local.charts}/nacos"
  namespace = kubernetes_namespace_v1.train_ticket.metadata[0].name
  timeout   = 900
  set = [
    { name = "nacos.db.host", value = "nacosdb-mysql-leader" },
    { name = "nacos.db.username", value = "nacos" },
    { name = "nacos.db.name", value = "nacos" },
    { name = "nacos.db.password", value = "Abcd1234#" },
  ]
  depends_on = [helm_release.nacosdb]
}

resource "helm_release" "rabbitmq" {
  name      = "rabbitmq"
  chart     = "${local.charts}/rabbitmq"
  namespace = kubernetes_namespace_v1.train_ticket.metadata[0].name
  timeout   = 900
}

resource "helm_release" "tsdb" {
  name      = "tsdb"
  chart     = "${local.charts}/mysql"
  namespace = kubernetes_namespace_v1.train_ticket.metadata[0].name
  timeout   = 900
  set = [
    { name = "mysql.mysqlUser", value = "ts" },
    { name = "mysql.mysqlPassword", value = "Ts_123456" },
    { name = "mysql.mysqlDatabase", value = "ts" },
  ]
}
```

`lab/terraform/lab/app.tf`:

```hcl
# The Train-Ticket objects `make deploy` applies, plus flagd and the traffic driver, decoded from the committed YAML.
# deploy.yaml.sample is the deployed file as-is: make deploy's sed (nacos -> nacos, rabbitmq -> rabbitmq) is a no-op.

locals {
  yamls = "${local.repo}/deployment/kubernetes-manifests/quickstart-k8s/yamls"

  telemetry = yamldecode(file(var.telemetry_file))
  logs_off  = toset(coalesce(try(local.telemetry.logs_off, null), []))
  apm_off   = toset(coalesce(try(local.telemetry.apm_off, null), []))

  flagd_docs = provider::kubernetes::manifest_decode_multi(file("${local.repo}/deployment/lab/flagd.yaml"))

  deployment_docs = concat(
    provider::kubernetes::manifest_decode_multi(file("${local.yamls}/deploy.yaml.sample")),
    [for d in local.flagd_docs : d if d.kind == "Deployment"],
    provider::kubernetes::manifest_decode_multi(file("${local.repo}/deployment/lab/traffic-driver.yaml")),
  )

  other_docs = concat(
    provider::kubernetes::manifest_decode_multi(file("${local.yamls}/secret.yaml")),
    provider::kubernetes::manifest_decode_multi(file("${local.yamls}/svc.yaml")),
    [for d in local.flagd_docs : d if d.kind != "Deployment"],
    [yamldecode(file("${local.repo}/templates/flagd-config.yaml"))],
  )

  # logs_off adds the pod annotation ad.datadoghq.com/logs_exclude; apm_off adds the pod label admission.datadoghq.com/enabled=false.
  deployments = {
    for d in local.deployment_docs : d.metadata.name => merge(d, {
      metadata = merge(d.metadata, { namespace = "train-ticket" })
      spec = merge(d.spec, {
        template = merge(d.spec.template, {
          metadata = merge(
            d.spec.template.metadata,
            {
              labels = merge(
                d.spec.template.metadata.labels,
                { for k, v in { "admission.datadoghq.com/enabled" = "false" } : k => v if contains(local.apm_off, d.metadata.name) },
              )
            },
            {
              for k, v in {
                annotations = merge(try(d.spec.template.metadata.annotations, {}), { "ad.datadoghq.com/logs_exclude" = "true" })
              } : k => v if contains(local.logs_off, d.metadata.name)
            },
          )
        })
      })
    })
  }

  others = {
    for d in local.other_docs : "${d.kind}/${d.metadata.name}" => merge(d, {
      metadata = merge(d.metadata, { namespace = "train-ticket" })
    })
  }

  unknown_services = sort(tolist(setsubtract(setunion(local.logs_off, local.apm_off), keys(local.deployments))))
}

resource "terraform_data" "telemetry_check" {
  lifecycle {
    precondition {
      condition     = length(local.unknown_services) == 0
      error_message = "lab/telemetry.yaml names unknown deployments: ${join(", ", local.unknown_services)}"
    }
  }
}

resource "kubernetes_manifest" "others" {
  for_each = local.others
  manifest = each.value
  field_manager {
    force_conflicts = true
  }
  depends_on = [kubernetes_namespace_v1.train_ticket]
}

resource "kubernetes_manifest" "deployments" {
  for_each = local.deployments
  manifest = each.value
  field_manager {
    force_conflicts = true
  }
  depends_on = [
    terraform_data.telemetry_check,
    kubernetes_manifest.others,
    helm_release.nacos,
    helm_release.rabbitmq,
    helm_release.tsdb,
  ]
}
```

`lab/terraform/lab/monitors.tf`:

```hcl
# Fault-agnostic monitors. No notification handle: lab/lab.sh reads their state through the API.
# Thresholds are initial values, tuned after the first baseline.

locals {
  apm_scope = "env:${var.lab_name}"
  k8s_scope = "kube_cluster_name:${var.lab_name},kube_namespace:train-ticket"
  log_scope = "kube_namespace:train-ticket service:tt-traffic-driver"

  apm_monitors = {
    java_latency = {
      name = "Java p95 latency by service", type = "query alert", critical = 2
      expr = "percentile(last_10m):p95:trace.servlet.request{${local.apm_scope}} by {service}"
    }
    voucher_latency = {
      name = "Voucher p95 latency", type = "query alert", critical = 2
      expr = "percentile(last_10m):p95:trace.tornado.request{${local.apm_scope}} by {service}"
    }
    java_errors = {
      name = "Java error rate by service", type = "query alert", critical = 0.1
      expr = "sum(last_10m):sum:trace.servlet.request.errors{${local.apm_scope}} by {service}.as_count() / sum:trace.servlet.request.hits{${local.apm_scope}} by {service}.as_count()"
    }
    voucher_errors = {
      name = "Voucher error rate", type = "query alert", critical = 0.1
      expr = "sum(last_10m):sum:trace.tornado.request.errors{${local.apm_scope}} by {service}.as_count() / sum:trace.tornado.request.hits{${local.apm_scope}} by {service}.as_count()"
    }
  }

  base_monitors = {
    oom_killed = {
      name = "OOMKilled by deployment", type = "query alert", critical = 1
      expr = "max(last_10m):max:kubernetes.containers.state.terminated{${local.k8s_scope},reason:oomkilled} by {kube_deployment}"
    }
    restarts = {
      name = "Restarts by deployment", type = "query alert", critical = 2
      expr = "change(max(last_10m),last_10m):sum:kubernetes.containers.restarts{${local.k8s_scope}} by {kube_deployment}"
    }
    edge_5xx = {
      name = "Edge 5xx by path", type = "log alert", critical = 2
      expr = "logs(\"${local.log_scope} @evt:outcome (@http_status:500 OR @http_status:502 OR @http_status:503 OR @http_status:504)\").index(\"*\").rollup(\"count\").by(\"@path\").last(\"10m\")"
    }
    edge_4xx = {
      name = "Edge 4xx by path", type = "log alert", critical = 5
      expr = "logs(\"${local.log_scope} @evt:outcome (@http_status:400 OR @http_status:401 OR @http_status:403 OR @http_status:404 OR @http_status:413)\").index(\"*\").rollup(\"count\").by(\"@path\").last(\"10m\")"
    }
    business_rejections = {
      name = "Business rejections by path", type = "log alert", critical = 20
      expr = "logs(\"${local.log_scope} @evt:outcome @tt_status:0\").index(\"*\").rollup(\"count\").by(\"@path\").last(\"10m\")"
    }
    fare_anomaly = {
      name = "Fare anomaly", type = "log alert", critical = 0
      expr = "logs(\"${local.log_scope} @evt:fare_anomaly\").index(\"*\").rollup(\"count\").last(\"10m\")"
    }
    apm_hosts_budget = {
      name = "APM hosts budget", type = "query alert", critical = var.apm_hosts_budget
      expr = "max(last_1h):max:datadog.estimated_usage.apm_hosts{*}"
    }
    apm_ingest_budget = {
      name = "APM ingestion budget (daily share)", type = "query alert", critical = floor(var.apm_ingest_gb_budget * 1000000000 / 30)
      expr = "sum(last_1d):sum:datadog.estimated_usage.apm.ingested_bytes{*}.as_count()"
    }
  }

  monitors = merge(local.base_monitors, { for k, v in local.apm_monitors : k => v if var.apm_enabled })
}

resource "datadog_monitor" "lab" {
  for_each = local.monitors

  name                = "[${var.lab_name}] ${each.value.name}"
  type                = each.value.type
  query               = "${each.value.expr} > ${each.value.critical}"
  message             = "Train-Ticket lab ${var.lab_name}: ${each.value.name}. No notification handle by design."
  require_full_window = false
  notify_no_data      = false
  tags                = ["lab:${var.lab_name}", "managed-by:terraform"]

  monitor_thresholds {
    critical = each.value.critical
  }
}
```

`lab/terraform/lab/outputs.tf`:

```hcl
output "monitor_ids" {
  description = "Monitor key => Datadog monitor id, read by lab/lab.sh test."
  value       = { for k, m in datadog_monitor.lab : k => m.id }
}
```

`lab/telemetry.yaml`:

```yaml
# Per-service telemetry switches. List Deployment names (the 46 ts-* services, tt-traffic-driver, flagd).
# Edit, then run `lab/lab.sh up` again; Kubernetes rolls the listed Deployments.
logs_off: []   # log collection off, e.g. [ts-news-service]
apm_off: []    # APM instrumentation off, e.g. [tt-traffic-driver]
```

- [ ] **Step 4: Lock the providers for the runner platforms**

Run: `mise exec terraform@1.16.4 -- terraform -chdir=lab/terraform/lab init -backend=false -input=false >/dev/null && mise exec terraform@1.16.4 -- terraform -chdir=lab/terraform/lab providers lock -platform=linux_amd64 -platform=linux_arm64 -platform=darwin_amd64 -platform=darwin_arm64 && grep -A1 '^provider' lab/terraform/lab/.terraform.lock.hcl`

Expected: datadog `4.22.0`, helm `3.3.0`, kubernetes `3.2.1`.

- [ ] **Step 5: Run the test and confirm it passes**

Run: `mise exec terraform@1.16.4 helm@3.22.0 -- uv run --no-project --with pytest==8.3.3 --with pyyaml==6.0.2 --with requests==2.32.3 --with tornado==6.5.10 --with pymysql==1.2.3 pytest lab/tests/test_terraform_lab.py -q`

Expected: `7 passed`.

- [ ] **Step 6: Commit**

```bash
git add lab/terraform/lab/versions.tf lab/terraform/lab/variables.tf lab/terraform/lab/infra.tf lab/terraform/lab/app.tf \
        lab/terraform/lab/monitors.tf lab/terraform/lab/outputs.tf lab/terraform/lab/.terraform.lock.hcl \
        lab/telemetry.yaml lab/tests/test_terraform_lab.py
git diff --staged --stat
git commit -m "feat(lab): Terraform stage for Train-Ticket, flagd, driver, monitors and telemetry switches"
```

---

### Task 3: `lab/lab.sh` (up, test, down)

**Files:**
- Create: `lab/lab.sh` (executable)
- Test: `lab/tests/stub_cli.py` (executable), `lab/tests/test_lab_sh.py`

**Interfaces:**
- Consumes:
  - Task 1's stage `datadog` and Task 2's stage `lab`, with the variables and output named above;
  - `lab/fault.sh on|off|status <F>`, which prints `tt-feat-NN true|false` for flag faults;
  - `hack/deploy/utils.sh`'s `update_tt_dp_cm`;
  - `make reset-deploy Namespace=<ns>`.
- Produces:
  - `lab/lab.sh up|test|down`;
  - step lines `PASS <id>[: …]`, `FAIL <id>: …` and `WARN G7: …`;
  - final lines `UP PASS …`, `TEST PASS …` and `DOWN PASS …`;
  - `REPORT …` lines from `test`.

  Task 4's docs test reads the step ids from the `pass`/`fail` calls and the inputs from the `for v in …; do` loop.

- [ ] **Step 1: Write the stub and the failing tests**

`lab/tests/stub_cli.py`:

```python
#!/usr/bin/env python3
"""Stand-in for kubectl, terraform, curl, make, sleep and date in the lab.sh tests.

Rules come from $STUB_RULES: {"<command>": [{"match": [substrings], "stdout": "...", "exit": 0}, ...]}.
The first rule whose substrings all occur in the joined arguments wins. A rule with "seq" answers its
calls in order and repeats the last item. For curl, the key is "<METHOD> <URL>", the answer goes to the
-o file, and "http" (default 200) is printed for -w. A rule with "exists" logs whether that path exists.
Every call is appended to $STUB_LOG as a JSON list.
"""
import json
import os
import sys
from pathlib import Path

name = Path(sys.argv[0]).name
args = sys.argv[1:]
state = Path(os.environ["STUB_STATE"])

if name == "sleep":
    sys.exit(0)
if name == "date":
    clock = state / "clock"
    t = int(clock.read_text()) + 60 if clock.exists() else 1_000_000
    clock.write_text(str(t))
    print(t)
    sys.exit(0)

out_file = ""
if name == "curl":
    config = sys.stdin.read()
    method = args[args.index("-X") + 1]
    out_file = args[args.index("-o") + 1]
    key = f"{method} {args[-1]}"
    with open(state / "curl-stdin", "a") as f:
        f.write(config)
else:
    key = " ".join(args)

with open(os.environ["STUB_LOG"], "a") as f:
    f.write(json.dumps([name, *args]) + "\n")

rules = json.loads(Path(os.environ["STUB_RULES"]).read_text()).get(name, [])
for i, rule in enumerate(rules):
    if all(token in key for token in rule["match"]):
        if "exists" in rule:
            with open(os.environ["STUB_LOG"], "a") as f:
                f.write(json.dumps(["exists", rule["exists"], Path(rule["exists"]).exists()]) + "\n")
        items = rule.get("seq") or [rule]
        counter = state / f"{name}-{i}"
        n = int(counter.read_text()) if counter.exists() else 0
        counter.write_text(str(n + 1))
        item = items[min(n, len(items) - 1)]
        if name == "curl":
            Path(out_file).write_text(item.get("stdout", ""))
            print(item.get("http", 200), end="")
            sys.exit(0)
        sys.stdout.write(item.get("stdout", ""))
        sys.exit(item.get("exit", 0))

if name == "curl":
    Path(out_file).write_text("{}")
    print(200, end="")
sys.exit(0)
```

Run: `chmod +x lab/tests/stub_cli.py`

`lab/tests/test_lab_sh.py`:

```python
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
STUB = REPO / "lab" / "tests" / "stub_cli.py"
COMMANDS = ["kubectl", "terraform", "curl", "make", "sleep", "date"]
SECRET_API, SECRET_APP = "api-secret-123", "app-secret-456"
INPUTS = {
    "KUBE_CONTEXT": "lab-ctx", "LAB_NAME": "tt-lab-1", "DD_SITE": "datadoghq.eu",
    "DD_API_KEY": SECRET_API, "DD_APP_KEY": SECRET_APP, "APM_HOSTS_BUDGET": "4", "APM_INGEST_GB_BUDGET": "150",
}


@pytest.fixture
def lab(tmp_path):
    """A copy of the parts of the repo lab.sh touches, with every external command stubbed."""
    root = tmp_path / "repo"
    for rel in ["lab/lab.sh", "hack/deploy/utils.sh", "hack/deploy/gen-mysql-secret.sh",
                "deployment/kubernetes-manifests/quickstart-k8s/yamls/deploy.yaml.sample"]:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, root / rel)
    fault = root / "lab" / "fault.sh"
    fault.write_text('#!/usr/bin/env bash\necho "fault.sh $*" >> "$STUB_LOG"\n'
                     'case "$1" in on) echo "tt-feat-22 true" ;; off) echo "tt-feat-22 false" ;; status) echo "x false" ;; esac\n')
    fault.chmod(0o755)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for command in COMMANDS:
        (bin_dir / command).symlink_to(STUB)
    state = tmp_path / "state"
    state.mkdir()

    class Lab:
        path = root
        log = tmp_path / "calls.log"
        rules_file = tmp_path / "rules.json"

        def run(self, script, rules, env=INPUTS):
            self.rules_file.write_text(json.dumps(rules))
            self.log.write_text("")
            full_env = {
                "PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(tmp_path), "TMPDIR": str(tmp_path),
                "STUB_RULES": str(self.rules_file), "STUB_LOG": str(self.log), "STUB_STATE": str(state), **env,
            }
            return subprocess.run(["bash", "-c", f'source "{root}/lab/lab.sh"; {script}'],
                                  env=full_env, capture_output=True, text=True)

        def calls(self):
            return [json.loads(line) for line in self.log.read_text().splitlines()]

        def curl_stdin(self):
            f = state / "curl-stdin"
            return f.read_text() if f.exists() else ""

    return Lab()


def test_script_parses():
    subprocess.run(["bash", "-n", str(REPO / "lab" / "lab.sh")], check=True)


def test_missing_inputs_are_all_named(lab):
    r = lab.run("require_inputs", {}, env={"LAB_NAME": "tt-lab-1"})
    assert r.returncode == 1
    assert "FAIL P0: missing inputs: KUBE_CONTEXT DD_SITE DD_API_KEY DD_APP_KEY APM_HOSTS_BUDGET APM_INGEST_GB_BUDGET" in r.stderr


@pytest.mark.parametrize("name", ["TT_Lab", "-lab", "lab-", "x" * 41])
def test_lab_name_must_be_a_dns_label(lab, name):
    r = lab.run("require_inputs", {}, env={**INPUTS, "LAB_NAME": name})
    assert r.returncode == 1 and "FAIL P0: LAB_NAME" in r.stderr


def test_apm_enabled_defaults_to_true_and_rejects_other_values(lab):
    assert "APM=true" in lab.run('require_inputs; echo "APM=$APM_ENABLED"', {}).stdout
    r = lab.run("require_inputs", {}, env={**INPUTS, "APM_ENABLED": "yes"})
    assert r.returncode == 1 and "APM_ENABLED" in r.stderr


def daemonsets(*items):
    return json.dumps({"items": [
        {"metadata": {"namespace": ns, "name": name, "labels": labels},
         "spec": {"template": {"spec": {"containers": [{"image": image}]}}}}
        for ns, name, labels, image in items]})


NO_DATADOG_NS = {"match": ["get", "namespace", "datadog"], "exit": 1}
NODES = {"match": ["get", "nodes", "jsonpath"], "stdout": "node-a node-b"}


@pytest.mark.parametrize("case, rules, install, reason", [
    ("own state",
     {"terraform": [{"match": ["state", "list"], "stdout": "helm_release.operator\n"}]},
     "true", "installed by this lab"),
    ("foreign by label",
     {"kubectl": [{"match": ["get", "daemonsets"], "stdout": daemonsets(
         ("monitoring", "dd", {"agent.datadoghq.com/component": "agent"}, "example.com/custom:1"))}]},
     "false", "monitoring/dd"),
    ("foreign by image",
     {"kubectl": [{"match": ["get", "daemonsets"], "stdout": daemonsets(
         ("kube-system", "datadog", {}, "gcr.io/datadoghq/agent:7.83.3"))}]},
     "false", "kube-system/datadog"),
    ("host install",
     {"kubectl": [{"match": ["get", "daemonsets"], "stdout": daemonsets(
         ("kube-system", "cluster-agent-lookalike", {}, "gcr.io/datadoghq/cluster-agent:7.83.3"))},
         NODES, {"match": ["tt-lab-probe run", "node-b"], "exit": 0}, {"match": ["tt-lab-probe run"], "exit": 1}, NO_DATADOG_NS]},
     "false", "node-b"),
    ("none",
     {"kubectl": [{"match": ["get", "daemonsets"], "stdout": daemonsets()}, NODES,
                  {"match": ["tt-lab-probe run"], "exit": 1}, NO_DATADOG_NS]},
     "true", "no Agent found"),
])
def test_agent_decision(lab, case, rules, install, reason):
    r = lab.run('p5_agent; echo "INSTALL=$INSTALL_AGENT"', rules)
    assert r.returncode == 0, r.stderr
    assert f"INSTALL={install}" in r.stdout, case
    assert reason in r.stdout, case


def test_agent_install_refuses_a_datadog_namespace_owned_by_someone_else(lab):
    rules = {"kubectl": [{"match": ["get", "daemonsets"], "stdout": daemonsets()}, NODES, {"match": ["tt-lab-probe run"], "exit": 1},
                         {"match": ["get", "namespace", "datadog", "jsonpath"], "stdout": ""},
                         {"match": ["get", "namespace", "datadog"], "exit": 0}]}
    r = lab.run("p5_agent", rules)
    assert r.returncode == 1 and "FAIL P5" in r.stderr


def test_host_probe_mounts_etc_read_only_and_cleans_up(lab):
    rules = {"kubectl": [NODES, {"match": ["tt-lab-probe run"], "exit": 1}]}
    lab.run("host_agent_nodes", rules)
    runs = [c for c in lab.calls() if c[:1] == ["kubectl"] and "run" in c]
    assert len(runs) == 2
    overrides = json.loads(next(a for a in runs[0] if a.startswith("--overrides=")).split("=", 1)[1])
    volume = overrides["spec"]["volumes"][0]["hostPath"]
    assert volume == {"path": "/etc", "type": "Directory"}
    assert overrides["spec"]["containers"][0]["volumeMounts"][0]["readOnly"] is True
    assert any(c[:3] == ["kubectl", "delete", "namespace"] and "tt-lab-probe" in c for c in lab.calls())


@pytest.mark.parametrize("owner_rules, ok", [
    ([{"match": ["get", "namespace", "train-ticket"], "exit": 1}], True),
    ([{"match": ["jsonpath"], "stdout": "tt-lab-1"}], True),
    ([{"match": ["jsonpath"], "stdout": "other-lab"}], False),
    ([{"match": ["jsonpath"], "stdout": ""}], False),
])
def test_namespace_guard(lab, owner_rules, ok):
    r = lab.run("p4_namespace", {"kubectl": owner_rules})
    assert (r.returncode == 0) == ok, r.stderr


def test_telemetry_names_must_be_known(lab):
    rules = {"terraform": [{"match": ["console"], "stdout": '"[\\"ts-bogus\\"]"\n'}]}
    r = lab.run("p6_telemetry", rules)
    assert r.returncode == 1 and 'unknown deployments: ["ts-bogus"]' in r.stderr
    rules = {"terraform": [{"match": ["console"], "stdout": '"[]"\n'}]}
    assert lab.run("p6_telemetry", rules).returncode == 0


FLAGS_ON_22_AND_5 = """flags:
  tt-feat-05:
    state: ENABLED
    defaultVariant: "on"
  tt-feat-07:
    state: ENABLED
    defaultVariant: "off"
  tt-feat-22:
    state: ENABLED
    defaultVariant: "on"
"""


def test_faults_on_reads_flags_and_patches(lab):
    rules = {"kubectl": [
        {"match": ["configmap", "flagd-config"], "stdout": FLAGS_ON_22_AND_5},
        {"match": ["deployment", "ts-order-service", "command"], "stdout": '["java","-Xms1g"]'},
        {"match": ["deployment", "ts-ui-dashboard"], "stdout": "f15-nginx"},
    ]}
    out = lab.run("faults_on", rules).stdout.split()
    assert sorted(out) == ["F15", "F22", "F3"]  # tt-feat-05 is not a lab fault


def test_faults_off_switches_off_only_what_is_on(lab):
    rules = {"kubectl": [{"match": ["configmap", "flagd-config"], "stdout": FLAGS_ON_22_AND_5}]}
    r = lab.run("faults_off", rules)
    assert r.returncode == 0, r.stderr
    assert "fault.sh off F22" in lab.log.read_text()
    assert "off F3" not in lab.log.read_text()


@pytest.mark.parametrize("answers, sets", [(["151", "500"], 1), (["500"], 0)])
def test_mysql_connections_are_raised_only_when_low(lab, answers, sets):
    rules = {"kubectl": [
        {"match": ["tsdb-mysql-0", "SELECT"], "seq": [{"stdout": a} for a in answers]},
        {"match": ["SELECT"], "stdout": "500"},
    ]}
    r = lab.run("g3_mysql", rules)
    assert r.returncode == 0, r.stderr
    assert sum("SET GLOBAL max_connections = 500" in " ".join(c) for c in lab.calls()) == sets


def test_mysql_non_numeric_answer_fails(lab):
    r = lab.run("g3_mysql", {"kubectl": [{"match": ["SELECT"], "stdout": "ERROR 2002"}]})
    assert r.returncode == 1 and "FAIL G3" in r.stderr


def test_datadog_keys_travel_on_stdin_never_argv(lab):
    rules = {"curl": [{"match": ["/api/v1/validate"], "stdout": '{"valid": true}'},
                      {"match": ["/api/v1/monitor"], "stdout": "[]"}]}
    r = lab.run("p3_keys", rules)
    assert r.returncode == 0, r.stderr
    assert all(SECRET_API not in a and SECRET_APP not in a for c in lab.calls() for a in c)
    assert f'DD-API-KEY: {SECRET_API}' in lab.curl_stdin()


def test_invalid_api_key_fails(lab):
    r = lab.run("p3_keys", {"curl": [{"match": ["/api/v1/validate"], "stdout": '{"errors": ["Forbidden"]}', "http": 403}]})
    assert r.returncode == 1 and "FAIL P3" in r.stderr


TEST_RULES_BASE = {
    "kubectl": [],
    "terraform": [
        {"match": ["console"], "stdout": '"false"\n'},
        {"match": ["output", "-json", "monitor_ids"], "stdout": json.dumps({"edge_5xx": "11", "voucher_errors": "12"})},
        {"match": ["state", "list"], "stdout": "helm_release.operator\n"},
    ],
}


def group(status):
    return {"stdout": json.dumps({"state": {"groups": {"@path:/getVoucher": {"status": status}}}})}


def with_curl(*rules):
    return {**TEST_RULES_BASE, "curl": list(rules)}


def test_f22_round_trip_passes_and_reports(lab):
    rules = with_curl(
        {"match": ["monitor/11?group_states=all"], "seq": [group("OK"), group("OK"), group("Alert"), group("OK")]},
        {"match": ["monitor/12"], "seq": [{"stdout": '{"overall_state": "OK"}'}, {"stdout": '{"overall_state": "Alert"}'}]},
        {"match": ["monitor/11"], "stdout": '{"overall_state": "OK"}'},
    )
    r = lab.run("trap cleanup EXIT; cmd_test", rules)
    assert r.returncode == 0, r.stderr
    faults = [line for line in lab.log.read_text().splitlines() if line.startswith("fault.sh")]
    assert faults == ["fault.sh on F22", "fault.sh off F22"]
    assert "PASS T3" in r.stdout and "REPORT F22 detect_s=" in r.stdout and "TEST PASS lab=tt-lab-1" in r.stdout
    assert "apm_error_monitor: alerted after" in r.stdout
    assert "REPORT uncovered: F1" in r.stdout


def test_f22_not_detected_fails_and_still_switches_the_fault_off(lab):
    rules = with_curl(
        {"match": ["monitor/11?group_states=all"], "stdout": group("OK")["stdout"]},
        {"match": ["monitor/1"], "stdout": '{"overall_state": "OK"}'},
    )
    r = lab.run("trap cleanup EXIT; cmd_test", rules)
    assert r.returncode == 1 and "FAIL T3" in r.stderr
    faults = [line for line in lab.log.read_text().splitlines() if line.startswith("fault.sh")]
    assert faults == ["fault.sh on F22", "fault.sh off F22"]


def test_test_refuses_when_driver_logs_are_off(lab):
    rules = {"terraform": [{"match": ["console"], "stdout": '"true"\n'}]}
    r = lab.run("cmd_test", rules)
    assert r.returncode == 1 and "FAIL T0" in r.stderr
    assert "fault.sh" not in lab.log.read_text()


def down_rules(lab, datadog_state=""):
    deploy_yaml = str(lab.path / "deployment/kubernetes-manifests/quickstart-k8s/yamls/deploy.yaml")
    return {
        "kubectl": [
            {"match": ["get", "namespace", "train-ticket", "jsonpath"], "stdout": "tt-lab-1"},
            {"match": ["get", "namespace", "train-ticket"], "seq": [{"exit": 0}, {"exit": 1}]},
            {"match": ["get", "namespace", "datadog"], "exit": 1},
            {"match": ["mutatingwebhookconfiguration"], "exit": 1},
        ],
        "make": [{"match": ["reset-deploy", "Namespace=train-ticket"], "exists": deploy_yaml}],
        "terraform": [{"match": ["state", "list"], "stdout": datadog_state}],
        "curl": [{"match": ["monitor_tags=lab:tt-lab-1"], "stdout": "[]"}],
    }


def test_down_runs_native_reset_first_then_terraform(lab):
    r = lab.run("trap cleanup EXIT; cmd_down", down_rules(lab))
    assert r.returncode == 0, r.stderr
    calls = lab.calls()
    order = [c[0] if c[0] != "terraform" else f"terraform {c[2]}" for c in calls
             if c[0] in ("make", "terraform") and (c[0] == "make" or c[2] in ("destroy",))]
    assert order[0] == "make" and "terraform destroy" in order
    assert ["exists", str(lab.path / "deployment/kubernetes-manifests/quickstart-k8s/yamls/deploy.yaml"), True] in calls
    assert not (lab.path / "deployment/kubernetes-manifests/quickstart-k8s/yamls/deploy.yaml").exists()
    assert "PASS D3: Agent not installed by this lab; left alone" in r.stdout
    assert "DOWN PASS lab=tt-lab-1" in r.stdout


def test_down_keeps_a_deploy_yaml_it_did_not_generate(lab):
    existing = lab.path / "deployment/kubernetes-manifests/quickstart-k8s/yamls/deploy.yaml"
    existing.write_text("# from an earlier make deploy\n")
    r = lab.run("trap cleanup EXIT; cmd_down", down_rules(lab))
    assert r.returncode == 0, r.stderr
    assert existing.read_text() == "# from an earlier make deploy\n"


def test_down_destroys_the_agent_stage_only_when_it_is_ours(lab):
    r = lab.run("trap cleanup EXIT; cmd_down", down_rules(lab, datadog_state="helm_release.operator\n"))
    assert r.returncode == 0, r.stderr
    destroys = [c for c in lab.calls() if c[0] == "terraform" and "destroy" in c]
    assert [c[1] for c in destroys] == [f"-chdir={lab.path}/lab/terraform/lab", f"-chdir={lab.path}/lab/terraform/datadog"]


def test_agent_secret_keys_never_reach_argv(lab):
    rules = {"kubectl": [{"match": ["mutatingwebhookconfiguration"], "exit": 0}]}
    r = lab.run("stage_datadog", rules)
    assert r.returncode == 0, r.stderr
    secret = [c for c in lab.calls() if "secret" in c and "generic" in c]
    assert secret and any(a.startswith("--from-env-file=/dev/fd/") for a in secret[0])
    assert all(SECRET_API not in a and SECRET_APP not in a for c in lab.calls() for a in c)
    assert "PASS G1" in r.stdout
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `mise exec terraform@1.16.4 helm@3.22.0 -- uv run --no-project --with pytest==8.3.3 --with pyyaml==6.0.2 --with requests==2.32.3 --with tornado==6.5.10 --with pymysql==1.2.3 pytest lab/tests/test_lab_sh.py -q`

Expected: every test fails or errors, because `lab/lab.sh` does not exist.

- [ ] **Step 3: Write `lab/lab.sh`**

`lab/lab.sh`:

```bash
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
DEPLOY_YAML="$REPO/deployment/kubernetes-manifests/quickstart-k8s/yamls/deploy.yaml"
AGENT_IMAGE_RE='^(registry\.datadoghq\.com|(eu\.|asia\.)?gcr\.io/datadoghq|public\.ecr\.aws/datadog|datadoghq\.azurecr\.io|(docker\.io/)?datadog)/agent(:|@|$)'
PINNED_KUBECONFIG=""
GENERATED_DEPLOY_YAML=""
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
  if [ -n "$GENERATED_DEPLOY_YAML" ]; then rm -f "$DEPLOY_YAML"; fi
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
  printf '{"spec":{"nodeName":"%s","tolerations":[{"operator":"Exists"}],"volumes":[{"name":"etc","hostPath":{"path":"/etc","type":"Directory"}}],"containers":[{"name":"%s","image":"docker.io/library/busybox:1.37","stdin":true,"command":["test","-f","/host/etc/datadog-agent/datadog.yaml"],"volumeMounts":[{"name":"etc","mountPath":"/host/etc","readOnly":true}]}]}}' "$1" "$2"
}

# Prints the nodes whose OS has the Datadog Agent package config (/etc/datadog-agent/datadog.yaml).
host_agent_nodes() {
  local node pod found=""
  kubectl create namespace tt-lab-probe --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  kubectl label namespace tt-lab-probe --overwrite pod-security.kubernetes.io/enforce=privileged >/dev/null
  for node in $(kubectl get nodes -o jsonpath='{.items[*].metadata.name}'); do
    pod="probe-$RANDOM"
    if kubectl -n tt-lab-probe run "$pod" --rm -i --restart=Never --quiet --pod-running-timeout=3m \
      --image=docker.io/library/busybox:1.37 --overrides="$(probe_overrides "$node" "$pod")" >/dev/null 2>&1; then
      found="$found $node"
    fi
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
    kubectl -n "$NS" wait --for=condition=Available deployment --all --timeout=1200s >/dev/null || fail G5 "deployments not available after restart"
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

native_reset() {
  if [ ! -e "$DEPLOY_YAML" ]; then
    GENERATED_DEPLOY_YAML=1
    (cd "$REPO" && source hack/deploy/utils.sh && update_tt_dp_cm nacos rabbitmq)
  fi
  (cd "$REPO" && make reset-deploy Namespace="$NS") >"${TMPDIR:-/tmp}/lab-native-reset.log" 2>&1 || true
  if [ -n "$GENERATED_DEPLOY_YAML" ]; then
    rm -f "$DEPLOY_YAML"
    [ ! -e "$DEPLOY_YAML" ] || fail D1 "could not remove the generated $DEPLOY_YAML"
    GENERATED_DEPLOY_YAML=""
  fi
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
```

Run: `chmod +x lab/lab.sh`

- [ ] **Step 4: Run the tests and the shell linters**

Run: `mise exec terraform@1.16.4 helm@3.22.0 -- uv run --no-project --with pytest==8.3.3 --with pyyaml==6.0.2 --with requests==2.32.3 --with tornado==6.5.10 --with pymysql==1.2.3 pytest lab/tests/test_lab_sh.py -q && bash -n lab/lab.sh && mise exec shellcheck@0.11.0 -- shellcheck -S warning lab/lab.sh lab/fault.sh && echo lint-ok`

Expected: `33 passed`, then `lint-ok`.

- [ ] **Step 5: Commit**

```bash
git add lab/lab.sh lab/tests/stub_cli.py lab/tests/test_lab_sh.py
git diff --staged --stat
git commit -m "feat(lab): lab.sh up, test and down with preflight, Agent decision and live gates"
```

---

### Task 4: README run guide, docs test, runbook removal

**Files:**
- Modify: `lab/README.md` (full replacement below)
- Modify: `lab/tests/test_docs.py` (full replacement below)
- Delete: `lab/DEPLOYER.md`

**Interfaces:**
- Consumes:
  - `lab/lab.sh`'s step ids and input loop (Task 3);
  - the monitor names in `lab/terraform/lab/monitors.tf` (Task 2);
  - the fault list in `lab/fault.sh`.

- [ ] **Step 1: Replace the docs test**

`lab/tests/test_docs.py`:

```python
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FAULTS = ["F1", "F3", "F7", "F12", "F14", "F15", "F17", "F22"]
README = (REPO / "lab/README.md").read_text()
LAB_SH = (REPO / "lab/lab.sh").read_text()


def test_the_agent_runbook_is_gone():
    assert not (REPO / "lab/DEPLOYER.md").exists()


def test_readme_and_script_agree_on_the_fault_list():
    script = (REPO / "lab/fault.sh").read_text()
    for fault in FAULTS:
        assert re.search(rf"\b{fault}\b", script), fault
        assert f"| {fault} |" in README, fault


def test_readme_documents_every_input_and_command():
    loop = re.search(r"for v in ([A-Z_ ]+); do", LAB_SH)
    assert loop, "require_inputs loop not found"
    inputs = loop.group(1).split() + ["APM_ENABLED"]
    for name in inputs:
        assert f"| `{name}` |" in README, name
    for command in ("lab/lab.sh up", "lab/lab.sh test", "lab/lab.sh down"):
        assert command in README, command


def first_column_ids(text):
    rows = re.findall(r"^\| ([A-Z][0-9](?:, [A-Z][0-9])*) \|", text, re.M)
    return {step for row in rows for step in row.split(", ")}


def test_readme_explains_every_step_id_the_script_can_print():
    ids = set(re.findall(r"\b(?:pass|fail) ([A-Z][0-9])\b", LAB_SH))
    assert ids >= {"P0", "P5", "S3", "G7", "T3", "D4"}
    steps, troubleshooting = README.split("## Troubleshooting")
    assert ids <= first_column_ids(steps), ids - first_column_ids(steps)
    assert ids <= first_column_ids(troubleshooting), ids - first_column_ids(troubleshooting)


def test_readme_lists_every_monitor_terraform_creates():
    names = re.findall(r'name = "([^"]+)", type =', (REPO / "lab/terraform/lab/monitors.tf").read_text())
    assert len(names) == 12
    for name in names:
        assert f"| {name} |" in README, name


def test_readme_greps_the_field_the_driver_writes():
    assert '"evt":"outcome"' in README
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `mise exec terraform@1.16.4 helm@3.22.0 -- uv run --no-project --with pytest==8.3.3 --with pyyaml==6.0.2 --with requests==2.32.3 --with tornado==6.5.10 --with pymysql==1.2.3 pytest lab/tests/test_docs.py -q`

Expected: several failures: `DEPLOYER.md` still exists, and the README lacks the inputs, step tables and monitor list.

- [ ] **Step 3: Delete the runbook and replace the README**

Run: `git rm lab/DEPLOYER.md`

`lab/README.md`:

````markdown
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
3. if this lab installed the Agent: `kubectl delete datadogagent -n datadog datadog`, `helm -n datadog uninstall datadog-operator`, `kubectl delete namespace datadog`;
4. delete the monitors tagged `lab:<LAB_NAME>` in Datadog.

## Build and test

- **Images:** `.github/workflows/lab-images.yaml` builds the six changed services and the driver to `ghcr.io/rajagopal-epistak/*:lab` on push.
- **Java:** `hack/lab/mvn.sh <module> test`.
- **Python, shell and Terraform:** `mise exec terraform@1.16.4 helm@3 -- uv run --no-project --with pytest==8.3.3 --with pyyaml==6.0.2 --with requests==2.32.3 --with tornado==6.5.10 --with pymysql==1.2.3 pytest lab traffic-driver ts-voucher-service/tests -q`.
- **auto-query:** `traffic-driver/autoquery/` is an unmodified copy of FudanSELab/train-ticket-auto-query at `9d5bc2d`.
````

- [ ] **Step 4: Run the test and confirm it passes**

Run: `mise exec terraform@1.16.4 helm@3.22.0 -- uv run --no-project --with pytest==8.3.3 --with pyyaml==6.0.2 --with requests==2.32.3 --with tornado==6.5.10 --with pymysql==1.2.3 pytest lab/tests/test_docs.py -q`

Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add lab/README.md lab/tests/test_docs.py
git diff --staged --stat
git commit -m "docs(lab): README run guide for lab.sh; retire the agent runbook"
```

---

### Task 5: Whole-branch verification sweep

- [ ] **Step 1: Run every Python, shell and Terraform test**

Run: `mise exec terraform@1.16.4 helm@3.22.0 -- uv run --no-project --with pytest==8.3.3 --with pyyaml==6.0.2 --with requests==2.32.3 --with tornado==6.5.10 --with pymysql==1.2.3 pytest lab traffic-driver ts-voucher-service/tests -q`

Expected: `81 passed`: 32 from the earlier suites, plus 3 + 7 + 33 + 6 new.

- [ ] **Step 2: Lint the scripts**

Run: `bash -n lab/lab.sh lab/fault.sh && mise exec shellcheck@0.11.0 -- shellcheck -S warning lab/lab.sh lab/fault.sh && echo lint-ok`

Expected: `lint-ok`.

- [ ] **Step 3: Check the branch touched only the planned files**

Run: `git status --short && git log --oneline master..HEAD && git diff --name-status master..HEAD | sort -k2`

Expected:
- `git status` prints nothing;
- 9 commits: the 4 spec commits already on the branch, the plan commit, and one each for Tasks 1–4;
- the name-status list is exactly:

```text
A	docs/superpowers/plans/2026-09-26-lab-deploy.md
A	docs/superpowers/specs/2026-09-26-lab-deploy-design.md
D	lab/DEPLOYER.md
M	lab/README.md
A	lab/lab.sh
A	lab/telemetry.yaml
A	lab/terraform/.gitignore
A	lab/terraform/datadog/.terraform.lock.hcl
A	lab/terraform/datadog/agent-chart/Chart.yaml
A	lab/terraform/datadog/agent-chart/templates/datadogagent.yaml
A	lab/terraform/datadog/agent-chart/values.yaml
A	lab/terraform/datadog/main.tf
A	lab/terraform/datadog/variables.tf
A	lab/terraform/datadog/versions.tf
A	lab/terraform/lab/.terraform.lock.hcl
A	lab/terraform/lab/app.tf
A	lab/terraform/lab/infra.tf
A	lab/terraform/lab/monitors.tf
A	lab/terraform/lab/outputs.tf
A	lab/terraform/lab/variables.tf
A	lab/terraform/lab/versions.tf
A	lab/tests/stub_cli.py
M	lab/tests/test_docs.py
A	lab/tests/test_lab_sh.py
A	lab/tests/test_terraform_datadog.py
A	lab/tests/test_terraform_lab.py
```


- [ ] **Step 4: Report and stop**

Report:
- the Step 1–3 outputs;
- every deviation from this plan, with the reason.

Do not push.
