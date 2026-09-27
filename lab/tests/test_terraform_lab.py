import base64
import json
import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
STAGE = REPO / "lab" / "terraform" / "lab"
CHARTS = REPO / "deployment" / "kubernetes-manifests" / "quickstart-k8s" / "charts"
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
        assert meta["annotations"] == {"ad.datadoghq.com/tags": '{"lab":"tt-lab-1"}'}
        assert "admission.datadoghq.com/enabled" not in meta["labels"]
    assert {name: meta for name, meta in evaluate("local.chart_pod_meta").items()} == {
        name: {"podLabels": {}, "podAnnotations": {}} for name in ("nacos", "nacosdb", "rabbitmq", "tsdb")}


def test_switches_land_on_exactly_the_listed_deployments(tmp_path):
    f = tmp_path / "telemetry.yaml"
    f.write_text("logs_off: [ts-news-service]\napm_off:\n  - tt-traffic-driver\n")
    env = {"TF_VAR_telemetry_file": str(f)}
    assert evaluate('local.deployments["ts-news-service"].spec.template.metadata.annotations', **env) == {
        "ad.datadoghq.com/tags": '{"lab":"tt-lab-1"}', "ad.datadoghq.com/logs_exclude": "true"}
    assert evaluate('local.deployments["tt-traffic-driver"].spec.template.metadata.labels', **env) == {
        "app": "tt-traffic-driver", "admission.datadoghq.com/enabled": "false"}
    assert evaluate('local.deployments["ts-basic-service"].spec.template.metadata', **env) == {
        "labels": {"app": "ts-basic-service"},
        "annotations": {"ad.datadoghq.com/tags": '{"lab":"tt-lab-1"}'}}


def test_every_pod_template_carries_the_lab_tag_annotation():
    # Every pod the lab creates gets ad.datadoghq.com/tags, so the Agent tags its metrics, logs and
    # traces with lab:<LAB_NAME> even when the Agent running on the node isn't this lab's.
    deployments = evaluate("local.deployments")
    assert len(deployments) == 46 + 2
    for name, d in deployments.items():
        assert d["spec"]["template"]["metadata"]["annotations"]["ad.datadoghq.com/tags"] == '{"lab":"tt-lab-1"}', name


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


def test_others_have_no_stringdata_and_secrets_carry_base64_data():
    others = evaluate("local.others")
    for key, manifest in others.items():
        assert "stringData" not in manifest, key
    secret = evaluate('local.others["Secret/ts-assurance-mysql"]')
    assert secret["data"]["ASSURANCE_MYSQL_HOST"] == base64.b64encode(b"tsdb-mysql-leader").decode()
    configmap = evaluate('local.others["ConfigMap/flagd-config"]')
    assert "data" in configmap and "stringData" not in configmap


def test_deployments_manifest_tolerates_a_restart_annotation():
    # computed_fields replaces, not extends, the provider's default (metadata.annotations, metadata.labels),
    # so spec.template.metadata.annotations must be listed alongside them, or a rollout-restart breaks re-apply.
    block = re.search(r'resource "kubernetes_manifest" "deployments" \{(.*?)\n\}', (STAGE / "app.tf").read_text(), re.S)
    assert block, "kubernetes_manifest.deployments block not found"
    computed = re.search(r"computed_fields\s*=\s*\[(.*?)\]", block.group(1), re.S)
    assert computed, "computed_fields not set on kubernetes_manifest.deployments"
    fields = {f.strip().strip('"') for f in computed.group(1).split(",") if f.strip()}
    assert fields == {"metadata.annotations", "metadata.labels", "spec.template.metadata.annotations"}


def test_oom_killed_monitor_watches_last_state():
    expr = evaluate("local.monitors")["oom_killed"]["expr"]
    assert "kubernetes.containers.last_state.terminated" in expr
    assert "kubernetes.containers.state.terminated" not in expr


def test_log_monitors_scope_the_driver_and_budget_is_a_daily_share():
    monitors = evaluate("local.monitors")
    assert "service:tt-traffic-driver" in monitors["edge_5xx"]["expr"]
    assert '.by("@path")' in monitors["edge_5xx"]["expr"]
    assert monitors["apm_ingest_budget"]["critical"] == 5_000_000_000


def test_k8s_and_log_scopes_key_off_the_lab_tag_not_cluster_or_namespace():
    # Two labs in one Datadog org must not see each other's metrics or logs.
    monitors = evaluate("local.monitors")
    assert "lab:tt-lab-1" in monitors["oom_killed"]["expr"]
    assert "kube_cluster_name" not in monitors["oom_killed"]["expr"]
    assert "kube_namespace:train-ticket" not in monitors["oom_killed"]["expr"]
    assert "lab:tt-lab-1 service:tt-traffic-driver" in monitors["edge_5xx"]["expr"]


def test_statefulset_releases_allow_for_one_replica_at_a_time():
    # Measured on the first live run: a 3-replica MySQL release took ~22 min (replicas start in order), past 900 s.
    infra = (STAGE / "infra.tf").read_text()
    timeouts = dict(re.findall(r'resource "helm_release" "(\w+)" \{.*?timeout\s*=\s*(\d+)', infra, re.S))
    assert {name: int(timeouts[name]) for name in ("nacosdb", "tsdb", "nacos")} == {"nacosdb": 1800, "tsdb": 1800, "nacos": 1800}


def test_helm_releases_upgrade_a_leftover_release_instead_of_refusing_it():
    # Live run: a release whose install timed out is not in state, so the next `up` hit "cannot re-use a name that
    # is still in use". upgrade_install makes it `helm upgrade --install`, which takes the leftover release over.
    infra = (STAGE / "infra.tf").read_text()
    blocks = re.findall(r'resource "helm_release" "(\w+)" \{(.*?)\n\}', infra, re.S)
    assert {name for name, body in blocks if re.search(r"upgrade_install\s*=\s*true", body)} == {"nacosdb", "nacos", "rabbitmq", "tsdb"}


def test_mysql_gets_a_root_account_for_ipv6_loopback_before_its_consumers():
    # Live run: xenon health-checks root@localhost:3306, which arrives from ::1 where pods have an IPv6 loopback; the
    # vendored chart only creates root@localhost and root@127.0.0.1, so no leader is elected (RadonDB's fix: #441).
    text = (STAGE / "infra.tf").read_text() + (STAGE / "app.tf").read_text()
    fix = re.search(r'resource "terraform_data" "mysql_root_ipv6" \{(.*?)\n\}', text, re.S)
    assert fix, "terraform_data.mysql_root_ipv6 missing"
    body = fix.group(1)
    assert "helm_release.nacosdb" in body and "helm_release.tsdb" in body
    assert "sql_log_bin=0" in body and "'root'@'::1'" in body and "WITH GRANT OPTION" in body
    nacos = re.search(r'resource "helm_release" "nacos" \{(.*?)\n\}', text, re.S).group(1)
    assert 'terraform_data.mysql_root_ipv6["nacosdb"]' in nacos
    deployments = re.search(r'resource "kubernetes_manifest" "deployments" \{(.*?)\n\}', text, re.S).group(1)
    assert "terraform_data.mysql_root_ipv6" in deployments


def heredoc_script(resource):
    infra = (STAGE / "infra.tf").read_text()
    body = re.search(rf'resource "terraform_data" "{resource}" \{{.*?command\s*=\s*<<-EOT\n(.*?)\n\s*EOT', infra, re.S).group(1)
    lines = body.splitlines()
    indent = min(len(line) - len(line.lstrip()) for line in lines if line.strip())
    return "\n".join(line[indent:] for line in lines)


@pytest.mark.parametrize("has_account, creates", [("1", False), ("0", True)])
def test_mysql_root_ipv6_step_skips_pods_that_already_have_the_account(tmp_path, has_account, creates):
    # Live run: on a re-run the cluster has a leader and xenon makes followers super_read_only, so CREATE USER fails
    # there (ERROR 1290) even though the account is already present from the first run.
    log = tmp_path / "kubectl.log"
    kubectl = tmp_path / "kubectl"
    kubectl.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$*" >> {log}\n'
        'case "$*" in\n'
        '  *"get pods"*) printf "pod/tsdb-mysql-0\\npod/tsdb-mysql-1\\n" ;;\n'
        '  *schemata*) printf "1\\t1\\n" ;;\n'
        f'  *"SELECT COUNT"*) echo {has_account} ;;\n'
        "esac\n")
    kubectl.chmod(0o755)
    r = subprocess.run(["bash", "-c", heredoc_script("mysql_root_ipv6")], capture_output=True, text=True,
                       env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "RELEASE": "tsdb"})
    assert r.returncode == 0, r.stderr
    created = [line for line in log.read_text().splitlines() if "CREATE USER" in line]
    assert len(created) == (2 if creates else 0)


@pytest.mark.parametrize("answers, ok, message, execs", [
    (["1\t1"], True, None, 1),              # the real server, init complete
    (["1\t0"], False, "PVC", 1),            # the real server, init cut short: fails at once
    (["0\t0", "", "1\t1"], True, None, 3),  # the temporary server, the gap between the two, then the real server
    (["0\t0"], False, "30 tries", 30),      # never the real server
])
def test_mysql_step_waits_for_the_real_server_then_fails_a_pod_whose_first_init_was_cut_short(
        tmp_path, answers, ok, message, execs):
    # Live run: the liveness probe killed mysqld during first-time init; the restart skipped init on the non-empty
    # datadir (no app user, no database), passed readiness (root's SELECT 1), and xenon made it leader. Readiness also
    # passes on the entrypoint's temporary server (networking off), so Helm's wait returns before the last pod's init.
    log = tmp_path / "kubectl.log"
    (tmp_path / "answers").write_text("".join(f"{a}\n" for a in answers))
    count = tmp_path / "count"
    (tmp_path / "kubectl").write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$*" >> {log}\n'
        'case "$*" in\n'
        '  *"get pods"*) echo pod/tsdb-mysql-0 ;;\n'
        f'  *schemata*) n=$(cat {count} 2>/dev/null || echo 0); echo $((n + 1)) > {count}\n'
        f'    total=$(wc -l < {tmp_path / "answers"}); a=$(sed -n "$(( n < total ? n + 1 : total ))p" {tmp_path / "answers"})\n'
        '    [ -n "$a" ] || exit 1; printf "%s\\n" "$a" ;;\n'
        '  *"SELECT COUNT"*) echo 0 ;;\n'
        "esac\n")
    (tmp_path / "sleep").write_text("#!/bin/sh\n")
    for name in ("kubectl", "sleep"):
        (tmp_path / name).chmod(0o755)
    r = subprocess.run(["bash", "-c", heredoc_script("mysql_root_ipv6")], capture_output=True, text=True,
                       env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "RELEASE": "tsdb"})
    assert (r.returncode == 0) == ok, r.stderr
    assert len([line for line in log.read_text().splitlines() if "schemata" in line]) == execs
    if not ok:
        assert "pod/tsdb-mysql-0" in r.stderr and message in r.stderr
        assert "CREATE USER" not in log.read_text()


def test_mysql_step_checks_the_pods_own_app_user_and_database(tmp_path):
    # Runs the real in-pod query: the fake kubectl executes what follows `--` locally, with the chart's env.
    log = tmp_path / "mysql.log"
    (tmp_path / "kubectl").write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        '  *"get pods"*) echo pod/tsdb-mysql-0 ;;\n'
        '  *exec*) while [ "$1" != "--" ]; do shift; done; shift; MYSQL_USER=ts MYSQL_DATABASE=ts exec "$@" ;;\n'
        "esac\n")
    (tmp_path / "mysql").write_text(
        f'#!/usr/bin/env bash\necho "$*" >> {log}\ncase "$*" in *skip_networking*) printf "1\\t1\\n" ;; *) echo 1 ;; esac\n')
    for name in ("kubectl", "mysql"):
        (tmp_path / name).chmod(0o755)
    r = subprocess.run(["bash", "-c", heredoc_script("mysql_root_ipv6")], capture_output=True, text=True,
                       env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "RELEASE": "tsdb"})
    assert r.returncode == 0, r.stderr
    queries = log.read_text()
    assert "@@skip_networking = 0" in queries and "user='ts'" in queries and "schema_name='ts'" in queries


def test_mysql_releases_give_first_init_a_startup_probe_budget():
    # Live run: first-time init took 107 s with six MySQL pods starting at once, past the liveness budget (30 s + 3 × 10 s).
    infra = (STAGE / "infra.tf").read_text()
    blocks = dict(re.findall(r'resource "helm_release" "(\w+)" \{(.*?)\n\}', infra, re.S))
    assert all("local.mysql_startup_probe" in blocks[name] for name in ("nacosdb", "tsdb"))
    probe = yaml.safe_load(evaluate("local.mysql_startup_probe"))["mysql"]["startupProbe"]
    assert probe["periodSeconds"] * probe["failureThreshold"] >= 600


@pytest.mark.parametrize("root_password", [[], ["--set", "mysql.allowEmptyRootPassword=false"]])
def test_mysql_chart_renders_a_startup_probe_with_the_liveness_command_only_when_set(root_password):
    def mysql_container(*args):
        r = subprocess.run(["helm", "template", "x", str(CHARTS / "mysql"), *root_password, *args],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        sts = next(d for d in yaml.safe_load_all(r.stdout) if d and d["kind"] == "StatefulSet")
        return next(c for c in sts["spec"]["template"]["spec"]["containers"] if c["name"] == "mysql")
    on = mysql_container("--set", "mysql.startupProbe.periodSeconds=10", "--set", "mysql.startupProbe.failureThreshold=60")
    assert on["startupProbe"]["exec"] == on["livenessProbe"]["exec"]
    assert on["startupProbe"]["timeoutSeconds"] == on["livenessProbe"]["timeoutSeconds"]
    assert (on["startupProbe"]["periodSeconds"], on["startupProbe"]["failureThreshold"]) == (10, 60)
    assert "startupProbe" not in mysql_container()


def test_chart_workloads_take_the_telemetry_switches(tmp_path):
    # Live run: SSI injected into, and the Agent collected logs from, the MySQL, Nacos and RabbitMQ pods too.
    f = tmp_path / "telemetry.yaml"
    f.write_text("logs_off: [nacos, tsdb]\napm_off: [rabbitmq, tsdb]\n")
    env = {"TF_VAR_telemetry_file": str(f)}
    assert evaluate("local.unknown_services", **env) == []
    assert evaluate("local.chart_pod_meta", **env) == {
        "nacos": {"podLabels": {}, "podAnnotations": {"ad.datadoghq.com/logs_exclude": "true"}},
        "nacosdb": {"podLabels": {}, "podAnnotations": {}},
        "rabbitmq": {"podLabels": {"admission.datadoghq.com/enabled": "false"}, "podAnnotations": {}},
        "tsdb": {"podLabels": {"admission.datadoghq.com/enabled": "false"},
                 "podAnnotations": {"ad.datadoghq.com/logs_exclude": "true"}},
    }


def test_every_helm_release_passes_its_switches():
    infra = (STAGE / "infra.tf").read_text()
    blocks = dict(re.findall(r'resource "helm_release" "(\w+)" \{(.*?)\n\}', infra, re.S))
    assert set(blocks) == {"nacosdb", "nacos", "rabbitmq", "tsdb"}
    for name, body in blocks.items():
        assert f'yamlencode(local.chart_pod_meta["{name}"])' in body, name


@pytest.mark.parametrize("chart, kind", [("mysql", "StatefulSet"), ("nacos", "StatefulSet"), ("rabbitmq", "Deployment")])
def test_charts_put_the_switches_on_their_pods_and_nothing_by_default(chart, kind):
    def pod_meta(*args):
        r = subprocess.run(["helm", "template", "x", str(CHARTS / chart), *args], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return next(d for d in yaml.safe_load_all(r.stdout) if d and d["kind"] == kind)["spec"]["template"]["metadata"]
    on = pod_meta("--set-json", 'podLabels={"admission.datadoghq.com/enabled":"false"}',
                  "--set-json", 'podAnnotations={"ad.datadoghq.com/logs_exclude":"true"}')
    assert on["labels"]["admission.datadoghq.com/enabled"] == "false"
    assert on["annotations"]["ad.datadoghq.com/logs_exclude"] == "true"
    off = pod_meta()
    assert "admission.datadoghq.com/enabled" not in off["labels"]
    assert "ad.datadoghq.com/logs_exclude" not in (off.get("annotations") or {})


def test_nacos_double_write_is_switched_off_before_the_services_on_every_apply():
    # Live run: Nacos 2.0.1 stayed in 1.x double-write mode ("upgrade check result false" every 5 s) and refused every
    # service's gRPC register. 2.0.1 has no startup property for it, and the switch lives in Nacos's memory.
    text = (STAGE / "infra.tf").read_text() + (STAGE / "app.tf").read_text()
    step = re.search(r'resource "terraform_data" "nacos_double_write_off" \{(.*?)\n\}', text, re.S)
    assert step, "terraform_data.nacos_double_write_off missing"
    body = step.group(1)
    assert "timestamp()" in body and "helm_release.nacos" in body
    assert "entry=doubleWriteEnabled&value=false" in body
    deployments = re.search(r'resource "kubernetes_manifest" "deployments" \{(.*?)\n\}', text, re.S).group(1)
    assert "terraform_data.nacos_double_write_off" in deployments


@pytest.mark.parametrize("codes, ok, execs", [([0], True, 3), ([1, 1, 0], True, 5), ([1], False, 30)])
def test_nacos_step_retries_each_member_until_the_switch_reads_off(tmp_path, codes, ok, execs):
    log = tmp_path / "kubectl.log"
    count = tmp_path / "count"
    kubectl = tmp_path / "kubectl"
    kubectl.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$*" >> {log}\n'
        'case "$*" in\n'
        '  *"get pods"*) printf "pod/nacos-0\\npod/nacos-1\\npod/nacos-2\\n" ;;\n'
        f'  *exec*) codes=({" ".join(map(str, codes))}); n=$(cat {count} 2>/dev/null || echo 0); echo $((n + 1)) > {count}\n'
        '    i=$(( n < ${#codes[@]} ? n : ${#codes[@]} - 1 )); exit "${codes[$i]}" ;;\n'
        "esac\n")
    kubectl.chmod(0o755)
    (tmp_path / "sleep").write_text("#!/bin/sh\n")
    (tmp_path / "sleep").chmod(0o755)
    r = subprocess.run(["bash", "-c", heredoc_script("nacos_double_write_off")], capture_output=True, text=True,
                       env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"})
    assert (r.returncode == 0) == ok, r.stderr
    assert len([line for line in log.read_text().splitlines() if line.startswith("-n train-ticket exec")]) == execs


@pytest.mark.parametrize("value, ok", [("false", True), ("true", False)])
def test_nacos_step_reads_the_switch_back_from_a_nacos_shaped_body(tmp_path, value, ok):
    # Runs the real in-pod script: the fake kubectl executes what follows `--` locally, against a fake curl that
    # answers the PUT with "ok" and the GET with compact JSON, the shape Nacos 2.0.1 returned on the live run.
    body = '{"masters":null,"adWeightMap":{},"defaultPushCacheMillis":10000,"doubleWriteEnabled":%s,"distroEnabled":true}'
    (tmp_path / "kubectl").write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        '  *"get pods"*) echo pod/nacos-0 ;;\n'
        '  *exec*) while [ "$1" != "--" ]; do shift; done; shift; exec "$@" ;;\n'
        "esac\n")
    (tmp_path / "curl").write_text(f"#!/usr/bin/env bash\ncase \"$*\" in *PUT*) echo ok ;; *) echo '{body % value}' ;; esac\n")
    (tmp_path / "sleep").write_text("#!/bin/sh\n")
    for name in ("kubectl", "curl", "sleep"):
        (tmp_path / name).chmod(0o755)
    r = subprocess.run(["bash", "-c", heredoc_script("nacos_double_write_off")], capture_output=True, text=True,
                       env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"})
    assert (r.returncode == 0) == ok, r.stderr
