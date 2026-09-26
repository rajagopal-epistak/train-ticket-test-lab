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
