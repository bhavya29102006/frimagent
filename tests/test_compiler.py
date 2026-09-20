"""Tests for agent/compiler.py scenario compiling and pairing rules."""

import json
from pathlib import Path
import yaml

from agent.compiler import compile_test
from agent.models import Expectation, TestCase, TestStep


def _create_mock_project(tmp_path: Path) -> Path:
    """Create a minimal project directory containing diagram.json."""
    project_dir = tmp_path / "mock_project"
    project_dir.mkdir()
    diagram = {
        "version": 1,
        "parts": [
            {"type": "wokwi-arduino-uno", "id": "uno"},
            {"type": "wokwi-dht22", "id": "dht1"},
        ],
        "connections": [
            ["dht1:VCC", "uno:5V", "red", ["v0"]],
            ["dht1:GND", "uno:GND.1", "black", ["v0"]],
            ["dht1:SDA", "uno:2", "green", ["v0"]],
        ],
    }
    (project_dir / "diagram.json").write_text(json.dumps(diagram), encoding="utf-8")
    return project_dir


def test_compile_alarm_pairing(tmp_path):
    """T07 Alarm: Non-temp expectation applies the next step before its wait-serial."""
    project_dir = _create_mock_project(tmp_path)
    out_dir = tmp_path / "out_t07"

    test_alarm = TestCase(
        id="T07",
        name="Alarm Overheat Test",
        category="abnormal",
        steps=[TestStep(set_temp=60.0)],
        expect=[
            Expectation(serial_contains="[ALARM] OVERHEAT"),
            Expectation(serial_contains="temp=60.0 fan=ON"),
        ],
        rationale="Verify overheat alarm",
    )

    scenario_file = compile_test(test_alarm, project_dir, out_dir)
    assert scenario_file.is_file()

    content = yaml.safe_load(scenario_file.read_text(encoding="utf-8"))
    assert content["name"] == "Alarm Overheat Test"
    steps = content["steps"]

    # Expected step sequence:
    # 1. wait-serial: [INFO] BOOT
    # 2. set-control: temperature=60
    # 3. wait-serial: [ALARM] OVERHEAT
    # 4. wait-serial: temp=60.0 fan=ON
    assert steps[0] == {"wait-serial": "[INFO] BOOT"}
    assert steps[1]["set-control"]["value"] == 60
    assert steps[2] == {"wait-serial": "[ALARM] OVERHEAT"}
    assert steps[3] == {"wait-serial": "temp=60.0 fan=ON"}


def test_compile_sequence_pairing(tmp_path):
    """T10 Sequence: Multi-step hysteresis sequence pairs temp=X with each matching step."""
    project_dir = _create_mock_project(tmp_path)
    out_dir = tmp_path / "out_t10"

    test_seq = TestCase(
        id="T10",
        name="Hysteresis Sequence Test",
        category="sequence",
        steps=[
            TestStep(set_temp=31.0),
            TestStep(set_temp=29.0),
        ],
        expect=[
            Expectation(serial_contains="temp=31.0 fan=ON"),
            Expectation(serial_contains="temp=29.0 fan=ON"),
        ],
        rationale="Verify hysteresis behavior",
    )

    scenario_file = compile_test(test_seq, project_dir, out_dir)
    content = yaml.safe_load(scenario_file.read_text(encoding="utf-8"))
    steps = content["steps"]

    # Expected step sequence:
    # 1. wait-serial: [INFO] BOOT
    # 2. set-control: 31
    # 3. wait-serial: temp=31.0 fan=ON
    # 4. set-control: 29
    # 5. wait-serial: temp=29.0 fan=ON
    assert steps[0] == {"wait-serial": "[INFO] BOOT"}
    assert steps[1]["set-control"]["value"] == 31
    assert steps[2] == {"wait-serial": "temp=31.0 fan=ON"}
    assert steps[3]["set-control"]["value"] == 29
    assert steps[4] == {"wait-serial": "temp=29.0 fan=ON"}


def test_compile_combination_pairing(tmp_path):
    """T13 Combination: Sequence with temp and non-temp expectations maintains correct order."""
    project_dir = _create_mock_project(tmp_path)
    out_dir = tmp_path / "out_t13"

    test_combo = TestCase(
        id="T13",
        name="Combination Test",
        category="combination",
        steps=[
            TestStep(set_temp=25.0),
            TestStep(set_temp=65.0),
            TestStep(set_temp=25.0),
        ],
        expect=[
            Expectation(serial_contains="temp=25.0 fan=OFF"),
            Expectation(serial_contains="[ALARM] OVERHEAT"),
            Expectation(serial_contains="temp=25.0 fan=OFF"),
        ],
        rationale="Test combination flow",
    )

    scenario_file = compile_test(test_combo, project_dir, out_dir)
    content = yaml.safe_load(scenario_file.read_text(encoding="utf-8"))
    steps = content["steps"]

    assert steps[0] == {"wait-serial": "[INFO] BOOT"}
    assert steps[1]["set-control"]["value"] == 25
    assert steps[2] == {"wait-serial": "temp=25.0 fan=OFF"}
    assert steps[3]["set-control"]["value"] == 65
    assert steps[4] == {"wait-serial": "[ALARM] OVERHEAT"}
    assert steps[5]["set-control"]["value"] == 25
    assert steps[6] == {"wait-serial": "temp=25.0 fan=OFF"}


def test_compile_disconnected_sensor(tmp_path):
    """Disconnected sensor removes dht1:SDA wire and skips all set-control steps."""
    project_dir = _create_mock_project(tmp_path)
    out_dir = tmp_path / "out_disconnected"

    test_disconnected = TestCase(
        id="T14",
        name="Sensor Disconnected",
        category="sensor_failure",
        sensor="disconnected",
        steps=[TestStep(set_temp=25.0)],
        expect=[
            Expectation(serial_contains="[ERROR] SENSOR_FAIL"),
            Expectation(serial_contains="fan=ON"),
        ],
        rationale="Verify fail-safe",
    )

    scenario_file = compile_test(test_disconnected, project_dir, out_dir)
    content = yaml.safe_load(scenario_file.read_text(encoding="utf-8"))
    steps = content["steps"]

    # Must contain ONLY wait-serial, no set-control
    assert steps[0] == {"wait-serial": "[INFO] BOOT"}
    assert steps[1] == {"wait-serial": "[ERROR] SENSOR_FAIL"}
    assert steps[2] == {"wait-serial": "fan=ON"}
    assert not any("set-control" in s for s in steps)

    # Check modified diagram.json
    diagram_file = out_dir / "diagram.json"
    assert diagram_file.is_file()
    diagram_data = json.loads(diagram_file.read_text(encoding="utf-8"))
    conns = diagram_data["connections"]
    # Verify dht1:SDA connection is gone, but VCC and GND remain
    assert not any("dht1:SDA" in str(c) for c in conns)
    assert any("dht1:VCC" in str(c) for c in conns)
    assert any("dht1:GND" in str(c) for c in conns)

    # Check wokwi.toml
    wokwi_toml = out_dir / "wokwi.toml"
    assert wokwi_toml.is_file()
    assert "firmware = 'firmware.hex'" in wokwi_toml.read_text(encoding="utf-8")
