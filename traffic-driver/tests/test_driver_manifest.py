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
