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
