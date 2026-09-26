import os
import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
STAGE = REPO / "lab" / "terraform" / "datadog"
VARS = {"TF_VAR_kubeconfig": "/nonexistent", "TF_VAR_lab_name": "tt-lab-1", "TF_VAR_dd_site": "datadoghq.eu",
        "TF_VAR_apm_enabled": "true", "TF_VAR_kubelet_tls_verify": "true"}


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


def test_kubelet_tls_verify_renders_true_and_false():
    for value, expected in (("true", True), ("false", False)):
        r = helm_template("datadog-agent", str(STAGE / "agent-chart"), "-n", "datadog",
                          "--set", "labName=tt-lab-1", "--set", "site=datadoghq.eu", "--set", "apmEnabled=false",
                          "--set", f"kubeletTlsVerify={value}")
        assert r.returncode == 0, r.stderr
        agent = yaml.safe_load(r.stdout)
        assert agent["spec"]["global"]["kubelet"]["tlsVerify"] is expected, value
