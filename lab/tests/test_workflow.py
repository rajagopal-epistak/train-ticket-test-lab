from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
MODULES = ["ts-basic-service", "ts-order-other-service", "ts-inside-payment-service", "ts-payment-service", "ts-cancel-service"]
ACTIONS = {
    "actions/checkout": "v7",
    "actions/setup-java": "v6",
    "docker/setup-buildx-action": "v4",
    "docker/login-action": "v4",
    "docker/build-push-action": "v7",
}


def workflow():
    return yaml.safe_load((REPO / ".github/workflows/lab-images.yaml").read_text())


def steps(job):
    return workflow()["jobs"][job]["steps"]


def test_triggers_and_permissions():
    wf = workflow()
    triggers = wf.get("on", wf.get(True))  # PyYAML reads the bare key `on` as True
    assert "workflow_dispatch" in triggers
    assert triggers["push"]["branches"] == ["master", "lab/**"]
    assert wf["permissions"] == {"contents": "read", "packages": "write"}


def test_service_matrix_is_the_five_changed_modules_and_each_builds_from_its_jar():
    assert workflow()["jobs"]["service"]["strategy"]["matrix"]["module"] == MODULES
    for module in MODULES:
        assert "target/" in (REPO / module / "Dockerfile").read_text(), module


def test_docker_job_builds_the_driver_and_voucher():
    assert workflow()["jobs"]["docker"]["strategy"]["matrix"]["include"] == [
        {"context": "traffic-driver", "image": "tt-traffic-driver"},
        {"context": "ts-voucher-service", "image": "ts-voucher-service"},
    ]


def test_images_are_amd64_and_tagged_lab_and_sha():
    for job in ("service", "docker"):
        push = next(s for s in steps(job) if s.get("uses", "").startswith("docker/build-push-action"))["with"]
        assert push["platforms"] == "linux/amd64"
        assert push["push"] is True
        assert ":lab" in push["tags"] and ":sha-${{ github.sha }}" in push["tags"]


def test_actions_are_pinned_to_current_majors():
    for job in ("service", "docker"):
        for step in steps(job):
            if "uses" in step:
                name, version = step["uses"].split("@")
                assert ACTIONS[name] == version, step["uses"]
