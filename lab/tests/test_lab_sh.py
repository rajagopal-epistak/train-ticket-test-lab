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
