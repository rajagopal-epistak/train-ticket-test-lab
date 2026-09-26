import json
import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
FAULT_SH = REPO / "lab" / "fault.sh"


def call(function_call, stdin=""):
    return subprocess.run(
        ["bash", "-c", f'source "{FAULT_SH}"; {function_call}'],
        input=stdin, capture_output=True, text=True, check=True,
    ).stdout


def flags_text():
    configmap = yaml.safe_load((REPO / "templates/flagd-config.yaml").read_text())
    return configmap["data"]["flags.yaml"]


def test_script_parses():
    subprocess.run(["bash", "-n", str(FAULT_SH)], check=True)


def test_flag_key_pads_the_number():
    assert call("flag_key F7") == "tt-feat-07"
    assert call("flag_key F22") == "tt-feat-22"


def test_flip_turns_on_only_the_named_flag():
    flags = yaml.safe_load(call("flip_flag_text tt-feat-07 on", flags_text()))["flags"]
    assert [name for name, flag in flags.items() if flag["defaultVariant"] == "on"] == ["tt-feat-07"]


def test_flip_off_restores_the_original():
    on = call("flip_flag_text tt-feat-12 on", flags_text())
    off = call("flip_flag_text tt-feat-12 off", on)
    assert yaml.safe_load(off) == yaml.safe_load(flags_text())


def test_limit_body_adds_one_directive_inside_the_api_location():
    conf = (REPO / "ts-ui-dashboard/nginx.conf").read_text()
    lines = call("limit_body_text", conf).splitlines()
    at = next(i for i, line in enumerate(lines) if "location /api/v1/ {" in line)
    assert lines[at + 1].strip() == "client_max_body_size 300;"
    assert sum("client_max_body_size" in line for line in lines) == 1


def test_f3_command_misconfigures_each_service_heap():
    services = call('echo "$F3_SERVICES"').split()
    assert services == ["ts-train-service", "ts-basic-service", "ts-order-service", "ts-order-other-service"]
    for service in services:
        assert json.loads(call(f"f3_command {service}")) == ["java", "-Xms1g", "-Xmx1g", "-jar", f"/app/{service}-1.0.jar"]


def test_unknown_fault_is_a_usage_error():
    result = subprocess.run(["bash", str(FAULT_SH), "on", "F2"], capture_output=True, text=True)
    assert result.returncode == 2
    assert "usage" in result.stderr
