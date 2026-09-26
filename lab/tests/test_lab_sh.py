import json
import os
import shutil
import signal
import subprocess
import time
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

        def _env(self, rules, env):
            self.rules_file.write_text(json.dumps(rules))
            self.log.write_text("")
            return {
                "PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(tmp_path), "TMPDIR": str(tmp_path),
                "STUB_RULES": str(self.rules_file), "STUB_LOG": str(self.log), "STUB_STATE": str(state), **env,
            }

        def run(self, script, rules, env=INPUTS):
            return subprocess.run(["bash", "-c", f'source "{root}/lab/lab.sh"; {script}'],
                                  env=self._env(rules, env), capture_output=True, text=True)

        def popen(self, script, rules, env=INPUTS):
            """Like run, but returns a live Popen so a test can signal the process mid-run."""
            return subprocess.Popen(["bash", "-c", f'source "{root}/lab/lab.sh"; {script}'],
                                    env=self._env(rules, env), text=True)

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


def test_kubelet_tls_verify_defaults_to_true_and_rejects_other_values(lab):
    assert "TLS=true" in lab.run('require_inputs; echo "TLS=$KUBELET_TLS_VERIFY"', {}).stdout
    r = lab.run("require_inputs", {}, env={**INPUTS, "KUBELET_TLS_VERIFY": "maybe"})
    assert r.returncode == 1 and "KUBELET_TLS_VERIFY" in r.stderr


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
         NODES, {"match": ["tt-lab-probe run", "node-b"], "stdout": "DATADOG_CONFIG_PRESENT\n"},
         {"match": ["tt-lab-probe run"], "stdout": "DATADOG_CONFIG_ABSENT\n"}, NO_DATADOG_NS]},
     "false", "node-b"),
    ("none",
     {"kubectl": [{"match": ["get", "daemonsets"], "stdout": daemonsets()}, NODES,
                  {"match": ["tt-lab-probe run"], "stdout": "DATADOG_CONFIG_ABSENT\n"}, NO_DATADOG_NS]},
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
    rules = {"kubectl": [NODES, {"match": ["tt-lab-probe run"], "stdout": "DATADOG_CONFIG_ABSENT\n"}]}
    r = lab.run("host_agent_nodes", rules)
    assert r.returncode == 0, r.stderr
    runs = [c for c in lab.calls() if c[:1] == ["kubectl"] and "run" in c]
    assert len(runs) == 2
    overrides = json.loads(next(a for a in runs[0] if a.startswith("--overrides=")).split("=", 1)[1])
    volume = overrides["spec"]["volumes"][0]["hostPath"]
    assert volume == {"path": "/etc", "type": "Directory"}
    assert overrides["spec"]["containers"][0]["volumeMounts"][0]["readOnly"] is True
    assert any(c[:3] == ["kubectl", "delete", "namespace"] and "tt-lab-probe" in c for c in lab.calls())


def test_host_probe_fails_p5_when_a_pod_cannot_run_at_all(lab):
    # kubectl run also returns non-zero for reasons that have nothing to do with the file being absent: an
    # image pull failure, a policy denial, a timed-out pod, or a leftover terminating probe from the last
    # run. Reading that as "no Agent" would let this lab install a second one, which D3 exists to prevent.
    rules = {"kubectl": [NODES, {"match": ["tt-lab-probe run"], "exit": 1}]}
    r = lab.run("host_agent_nodes", rules)
    assert r.returncode == 1 and "FAIL P5" in r.stderr
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


def test_err_trap_catches_an_unguarded_terraform_init_failure(lab):
    rules = {"terraform": [{"match": ["init"], "exit": 1}]}
    r = lab.run("trap on_err ERR; p6_telemetry", rules)
    assert r.returncode == 1 and "FAIL P6" in r.stderr


def test_err_trap_catches_an_unguarded_stage_datadog_setup_failure(lab):
    rules = {"kubectl": [{"match": ["create", "namespace", "datadog"], "exit": 1}]}
    r = lab.run("trap on_err ERR; stage_datadog", rules, env={**INPUTS, "APM_ENABLED": "true"})
    assert r.returncode == 1 and "FAIL S1" in r.stderr


def test_err_trap_catches_an_unguarded_g3_exec_failure(lab):
    rules = {"kubectl": [{"match": ["exec", "tsdb-mysql-0"], "exit": 1}]}
    r = lab.run("trap on_err ERR; g3_mysql", rules)
    assert r.returncode == 1 and "FAIL G3" in r.stderr


def test_err_trap_catches_a_timed_out_datadog_namespace_delete(lab):
    rules = {
        "kubectl": [
            {"match": ["get", "namespace", "train-ticket"], "exit": 1},
            {"match": ["get", "namespace", "datadog", "jsonpath"], "stdout": "tt-lab-1"},
            {"match": ["get", "namespace", "datadog"], "exit": 0},
            {"match": ["delete", "namespace", "datadog"], "exit": 1},
        ],
        "terraform": [{"match": ["state", "list"], "stdout": "helm_release.operator\n"}],
    }
    r = lab.run("trap cleanup EXIT; trap on_err ERR; cmd_down", rules)
    assert r.returncode == 1 and "FAIL D3" in r.stderr


def test_err_trap_catches_monitor_ids_lookup_failure_before_up_ran(lab):
    rules = {
        "terraform": [{"match": ["console"], "stdout": '"false"\n'},
                      {"match": ["output", "-json", "monitor_ids"], "exit": 1}],
    }
    r = lab.run("trap on_err ERR; cmd_test", rules)
    assert r.returncode == 1 and "FAIL T0" in r.stderr


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


def up_sequencing_rules(train_ticket_owner):
    """Rules for a cmd_up run that reaches S2/S3 with a foreign Agent (so stage_datadog never runs) and
    fails S3's apply immediately, so G2 onward need no stubbing at all."""
    if train_ticket_owner == "absent":
        owner_rules = [{"match": ["get", "namespace", "train-ticket"], "exit": 1}]
    else:
        owner_rules = [
            {"match": ["get", "namespace", "train-ticket", "jsonpath"], "stdout": train_ticket_owner},
            {"match": ["get", "namespace", "train-ticket"], "exit": 0},
        ]
    kubectl_rules = [
        *owner_rules,
        {"match": ["get", "nodes", "-o", "json"], "stdout": json.dumps({"items": [
            {"metadata": {"name": "node-a", "labels": {"kubernetes.io/arch": "amd64"}},
             "status": {"conditions": [{"type": "Ready", "status": "True"}]}}]})},
        {"match": ["get", "storageclass"], "stdout": json.dumps({"items": [
            {"metadata": {"annotations": {"storageclass.kubernetes.io/is-default-class": "true"}}}]})},
        {"match": ["get", "daemonsets"], "stdout": daemonsets(
            ("kube-system", "datadog", {}, "gcr.io/datadoghq/agent:7.83.3"))},
    ]
    if train_ticket_owner != "absent":
        # Only queried if the namespace exists: an active F22 for faults_off (S2) to switch off.
        kubectl_rules.append({"match": ["configmap", "flagd-config"], "stdout": FLAGS_ON_22_AND_5})
    return {
        "kubectl": kubectl_rules,
        "terraform": [
            {"match": ["version", "-json"], "stdout": json.dumps({"terraform_version": "1.16.4"})},
            {"match": ["console"], "stdout": '"[]"\n'},
            {"match": ["apply", "-auto-approve"], "exit": 1},
        ],
        "curl": [
            {"match": ["/api/v1/validate"], "stdout": '{"valid": true}'},
            {"match": ["/api/v1/monitor"], "stdout": "[]"},
        ],
    }


def mixed_lines(lab):
    """The raw call log, tolerant of the plain 'fault.sh ...' lines fault.sh's stub also appends."""
    return [line if line.startswith("fault.sh") else json.loads(line) for line in lab.log.read_text().splitlines()]


@pytest.mark.parametrize("owner, expect_fault_call", [("tt-lab-1", True), ("absent", False)])
def test_up_runs_s2_before_s3_only_when_the_namespace_exists(lab, owner, expect_fault_call):
    rules = up_sequencing_rules(owner)
    r = lab.run("trap cleanup EXIT; cmd_up", rules, env={**INPUTS, "APM_ENABLED": "false"})
    assert r.returncode == 1 and "FAIL S3" in r.stderr, r.stderr
    calls = mixed_lines(lab)
    fault_calls = [c for c in calls if isinstance(c, str)]
    if expect_fault_call:
        assert fault_calls == ["fault.sh off F22"]
        apply_index = next(i for i, c in enumerate(calls) if isinstance(c, list) and c[0] == "terraform" and "apply" in c)
        assert calls.index("fault.sh off F22") < apply_index
    else:
        assert fault_calls == []


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


def test_g5_fallback_waits_for_ts_basic_service_rollout_not_all_deployments(lab):
    # replicas:1 with the default RollingUpdate (maxUnavailable=0, maxSurge=1) keeps the old pod Available
    # throughout the restart, so `kubectl wait --for=condition=Available --all` returns at once; only
    # `rollout status` on the one deployment we sample actually waits for the new pod to replace the old.
    rules = {"kubectl": [
        {"match": ["get", "pods", "app=ts-basic-service"], "seq": [{"exit": 1}, {"stdout": "datadog-init"}]},
    ]}
    r = lab.run("g5_apm", rules, env={**INPUTS, "APM_ENABLED": "true", "INSTALL_AGENT": "true"})
    assert r.returncode == 0, r.stderr
    calls = lab.calls()
    assert any(c[0] == "kubectl" and "rollout" in c and "status" in c and "deployment/ts-basic-service" in c for c in calls)
    assert not any("--for=condition=Available" in c for c in calls)
    assert "PASS G5" in r.stdout


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


def test_driver_logs_seen_scopes_the_query_to_this_lab(lab):
    # Two labs in one Datadog org must not see each other's driver logs.
    rules = {"curl": [{"match": ["/api/v2/logs/events/search"], "stdout": '{"data": [{}]}'}]}
    r = lab.run("driver_logs_seen", rules)
    assert r.returncode == 0, r.stderr
    call = next(c for c in lab.calls() if c[0] == "curl" and "logs/events/search" in c[-1])
    body = call[call.index("--data") + 1]
    assert "lab:tt-lab-1 service:tt-traffic-driver" in body
    assert "kube_namespace" not in body


def test_g7_kubernetes_metric_check_scopes_to_the_lab_tag(lab):
    rules = {"curl": [{"match": ["/api/v1/query"], "stdout": '{"series": [1]}'},
                      {"match": ["/api/v2/logs/events/search"], "stdout": '{"data": [{}]}'}]}
    r = lab.run("g7_datadog", rules, env={**INPUTS, "APM_ENABLED": "false", "INSTALL_AGENT": "true"})
    assert r.returncode == 0, r.stderr
    call = next(c for c in lab.calls() if c[0] == "curl" and "/api/v1/query" in c[-1])
    assert "lab%3Att-lab-1" in call[-1]
    assert "kube_cluster_name" not in call[-1]


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


def test_test_clears_a_leftover_f22_before_the_baseline_check(lab):
    # A SIGKILL can't be trapped, so a prior test run may have left F22 on. test must clear it (S2's
    # faults_off logic) before T1's baseline check, not just at the end of a run that completes normally.
    rules = with_curl(
        {"match": ["monitor/11?group_states=all"], "seq": [group("OK"), group("OK"), group("Alert"), group("OK")]},
        {"match": ["monitor/12"], "seq": [{"stdout": '{"overall_state": "OK"}'}, {"stdout": '{"overall_state": "Alert"}'}]},
        {"match": ["monitor/11"], "stdout": '{"overall_state": "OK"}'},
    )
    rules["kubectl"] = [{"match": ["configmap", "flagd-config"], "stdout": FLAGS_ON_22_AND_5}]
    r = lab.run("trap cleanup EXIT; cmd_test", rules)
    assert r.returncode == 0, r.stderr
    faults = [line for line in lab.log.read_text().splitlines() if line.startswith("fault.sh")]
    assert faults == ["fault.sh off F22", "fault.sh on F22", "fault.sh off F22"]


def test_t2_failure_still_switches_f22_off(lab):
    fault = lab.path / "lab" / "fault.sh"
    fault.write_text('#!/usr/bin/env bash\necho "fault.sh $*" >> "$STUB_LOG"\n'
                      'case "$1" in on) echo "tt-feat-22 unexpected" ;; off) echo "tt-feat-22 false" ;; esac\n')
    fault.chmod(0o755)
    rules = with_curl({"match": ["monitor/11?group_states=all"], "stdout": group("OK")["stdout"]})
    r = lab.run("trap cleanup EXIT; cmd_test", rules)
    assert r.returncode == 1 and "FAIL T2" in r.stderr
    assert "fault.sh off F22" in lab.log.read_text()


def test_a_signal_mid_run_still_switches_f22_off(lab):
    # SIGKILL, including an agent tool's timeout, can't be trapped. Any other signal can: bash still runs
    # the EXIT trap before it dies, as long as it's blocked (not mid-syscall) when the signal arrives.
    # /bin/sleep, not the stubbed one, so the process is genuinely blocked when the signal is sent.
    p = lab.popen("trap cleanup EXIT; F22_ON=1; /bin/sleep 5", {})
    time.sleep(0.5)
    p.send_signal(signal.SIGTERM)
    rc = p.wait(timeout=5)
    assert rc != 0
    assert "fault.sh off F22" in lab.log.read_text()


def test_test_refuses_when_driver_logs_are_off(lab):
    rules = {"terraform": [{"match": ["console"], "stdout": '"true"\n'}]}
    r = lab.run("cmd_test", rules)
    assert r.returncode == 1 and "FAIL T0" in r.stderr
    assert "fault.sh" not in lab.log.read_text()


def down_rules(lab, datadog_state="", train_ticket_owner="tt-lab-1", datadog_namespace_exit=1):
    deploy_yaml = str(lab.path / "deployment/kubernetes-manifests/quickstart-k8s/yamls/deploy.yaml")
    if train_ticket_owner == "absent":
        owner_rules = [{"match": ["get", "namespace", "train-ticket"], "exit": 1}]
    else:
        owner_rules = [
            {"match": ["get", "namespace", "train-ticket", "jsonpath"], "stdout": train_ticket_owner},
            {"match": ["get", "namespace", "train-ticket"], "seq": [{"exit": 0}, {"exit": 1}]},
        ]
    return {
        "kubectl": [
            *owner_rules,
            {"match": ["get", "namespace", "datadog"], "exit": datadog_namespace_exit},
            {"match": ["get", "mutatingwebhookconfiguration"], "exit": 1},
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
    assert ["exists", str(lab.path / "deployment/kubernetes-manifests/quickstart-k8s/yamls/deploy.yaml"), False] in calls
    assert not (lab.path / "deployment/kubernetes-manifests/quickstart-k8s/yamls/deploy.yaml").exists()
    assert "PASS D3: Agent not installed by this lab; left alone" in r.stdout
    assert "DOWN PASS lab=tt-lab-1" in r.stdout


def test_down_keeps_a_deploy_yaml_it_did_not_generate(lab):
    existing = lab.path / "deployment/kubernetes-manifests/quickstart-k8s/yamls/deploy.yaml"
    existing.write_text("# from an earlier make deploy\n")
    r = lab.run("trap cleanup EXIT; cmd_down", down_rules(lab))
    assert r.returncode == 0, r.stderr
    assert existing.read_text() == "# from an earlier make deploy\n"


@pytest.mark.parametrize("label", ["other-lab", ""], ids=["foreign", "unlabelled"])
def test_down_skips_native_reset_on_a_foreign_or_unlabelled_namespace(lab, label):
    r = lab.run("trap cleanup EXIT; cmd_down", down_rules(lab, train_ticket_owner=label))
    assert r.returncode == 0, r.stderr
    assert not any(c[0] == "make" for c in lab.calls())
    assert "DOWN PASS lab=tt-lab-1" in r.stdout


def test_down_leaves_a_foreign_datadog_namespace_alone(lab):
    r = lab.run("trap cleanup EXIT; cmd_down", down_rules(lab, datadog_namespace_exit=0))
    assert r.returncode == 0, r.stderr
    assert not any(c[0] == "kubectl" and c[1] == "delete" and "datadog" in " ".join(c) for c in lab.calls())
    assert "PASS D3: Agent not installed by this lab; left alone" in r.stdout
    assert "DOWN PASS lab=tt-lab-1" in r.stdout


def test_down_destroys_the_agent_stage_only_when_it_is_ours(lab):
    r = lab.run("trap cleanup EXIT; cmd_down", down_rules(lab, datadog_state="helm_release.operator\n"))
    assert r.returncode == 0, r.stderr
    destroys = [c for c in lab.calls() if c[0] == "terraform" and "destroy" in c]
    assert [c[1] for c in destroys] == [f"-chdir={lab.path}/lab/terraform/lab", f"-chdir={lab.path}/lab/terraform/datadog",
                                        f"-chdir={lab.path}/lab/terraform/datadog"]
    deletes = [c for c in lab.calls() if c[:2] == ["kubectl", "delete"] and "mutatingwebhookconfiguration" in c]
    assert any("datadog-webhook" in c and "--ignore-not-found" in c for c in deletes), lab.calls()
    delete_index = lab.calls().index(deletes[0])
    destroy_index = lab.calls().index(destroys[-1])
    assert delete_index > destroy_index


def test_down_destroys_the_agent_release_before_the_rest_and_waits_between(lab):
    # keepCrds is unset, so destroying the Operator release deletes the DatadogAgentInternal CRD. Destroying
    # it before the Operator has finalized that object hangs the CRD delete, so the agent release is
    # destroyed alone first, then lab.sh waits for its DatadogAgentInternal objects to go.
    r = lab.run("trap cleanup EXIT; cmd_down", down_rules(lab, datadog_state="helm_release.operator\n"))
    assert r.returncode == 0, r.stderr
    calls = lab.calls()
    destroys = [c for c in calls if c[0] == "terraform" and "destroy" in c]
    assert "-target=helm_release.agent" in destroys[1] and "-target=helm_release.agent" not in destroys[2]
    waits = [c for c in calls if c[:2] == ["kubectl", "wait"] and "datadogagentinternals" in c]
    assert any("--for=delete" in c and "--all" in c for c in waits), calls
    assert calls.index(destroys[1]) < calls.index(waits[0]) < calls.index(destroys[2])


def test_down_fails_d3_when_datadogagentinternals_do_not_go_away(lab):
    rules = down_rules(lab, datadog_state="helm_release.operator\n")
    rules["kubectl"].append({"match": ["wait", "datadogagentinternals"], "exit": 1})
    r = lab.run("trap cleanup EXIT; cmd_down", rules)
    assert r.returncode == 1 and "FAIL D3" in r.stderr


def test_agent_secret_keys_never_reach_argv(lab):
    rules = {"kubectl": [{"match": ["mutatingwebhookconfiguration"], "exit": 0}]}
    r = lab.run("stage_datadog", rules)
    assert r.returncode == 0, r.stderr
    secret = [c for c in lab.calls() if "secret" in c and "generic" in c]
    assert secret and any(a.startswith("--from-env-file=/dev/fd/") for a in secret[0])
    assert all(SECRET_API not in a and SECRET_APP not in a for c in lab.calls() for a in c)
    assert "PASS G1" in r.stdout
