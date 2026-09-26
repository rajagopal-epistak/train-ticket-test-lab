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
    inputs = loop.group(1).split() + ["APM_ENABLED", "KUBELET_TLS_VERIFY"]
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
