"""Unit tests for Multi-Simulator Architecture (agent/simulators/)."""

from pathlib import Path
import pytest

from agent.models import Expectation, TestCase, TestStep
from agent.orchestrator import run_all
from agent.simulators import (
    NativeHostSimulator,
    PythonSimulator,
    VirtualMockSimulator,
    WokwiSimulator,
    detect_firmware_language,
    get_simulator,
    list_available_simulators,
)


def test_detect_firmware_language():
    """Detects programming language from extension or code snippet."""
    assert detect_firmware_language("main.cpp") == "cpp"
    assert detect_firmware_language("driver.c") == "c"
    assert detect_firmware_language("sketch.ino") == "ino"
    assert detect_firmware_language("controller.py") == "python"
    assert detect_firmware_language("import sys\ndef run(): pass") == "python"
    assert detect_firmware_language("void setup() { pinMode(13, OUTPUT); }") == "ino"


def test_list_and_get_simulators():
    """Simulator registry contains wokwi, virtual_mock, native_c, and python_sim."""
    sims = list_available_simulators()
    sim_ids = {s["id"] for s in sims}
    assert "wokwi" in sim_ids
    assert "virtual_mock" in sim_ids
    assert "native_c" in sim_ids
    assert "python_sim" in sim_ids

    # get_simulator returns appropriate simulator
    assert isinstance(get_simulator("wokwi"), WokwiSimulator)
    assert isinstance(get_simulator("virtual_mock"), VirtualMockSimulator)
    assert isinstance(get_simulator("native_c"), NativeHostSimulator)
    assert isinstance(get_simulator("python_sim"), PythonSimulator)
    # Unknown simulator falls back to virtual_mock
    assert isinstance(get_simulator("unknown_xyz"), VirtualMockSimulator)


def test_virtual_mock_simulator_normal_pass(tmp_path):
    """VirtualMockSimulator executes a normal room temp test and passes."""
    fw_dir = tmp_path / "firmware"
    src_dir = fw_dir / "src"
    src_dir.mkdir(parents=True)
    (src_dir / "main.cpp").write_text("void setup() {}\nvoid loop() {}", encoding="utf-8")

    test = TestCase(
        id="T01",
        name="Normal Room Temp",
        category="normal",
        steps=[TestStep(set_temp=25.0, wait_ms=2500)],
        expect=[Expectation(serial_contains="temp=25.0 fan=OFF")],
        rationale="Room temp fan off",
        round=0,
    )

    sim = VirtualMockSimulator()
    res = sim.run_test(test=test, firmware_dir=fw_dir, run_dir=tmp_path)

    assert res.test_id == "T01"
    assert res.status == "PASS"
    assert any("temp=25.0 fan=OFF" in line for line in res.observed_lines)


def test_virtual_mock_simulator_overheat_alarm(tmp_path):
    """VirtualMockSimulator triggers OVERHEAT alarm for temp > 60.0."""
    fw_dir = tmp_path / "firmware"
    src_dir = fw_dir / "src"
    src_dir.mkdir(parents=True)
    (src_dir / "main.cpp").write_text("void setup() {}\nvoid loop() {}", encoding="utf-8")

    test = TestCase(
        id="T02",
        name="Overheat Test",
        category="abnormal",
        steps=[TestStep(set_temp=65.0, wait_ms=2500)],
        expect=[
            Expectation(serial_contains="[ALARM] OVERHEAT"),
            Expectation(serial_contains="temp=65.0 fan=ON"),
        ],
        rationale="Overheat condition",
        round=0,
    )

    sim = VirtualMockSimulator()
    res = sim.run_test(test=test, firmware_dir=fw_dir, run_dir=tmp_path)

    assert res.status == "PASS"
    assert any("[ALARM] OVERHEAT" in line for line in res.observed_lines)


def test_python_simulator_fallback(tmp_path):
    """PythonSimulator runs test and produces valid result."""
    fw_dir = tmp_path / "firmware"
    src_dir = fw_dir / "src"
    src_dir.mkdir(parents=True)
    (src_dir / "main.py").write_text("# Embedded Python", encoding="utf-8")

    test = TestCase(
        id="T01",
        name="Python Test",
        category="normal",
        steps=[TestStep(set_temp=25.0, wait_ms=2500)],
        expect=[Expectation(serial_contains="fan=OFF")],
        rationale="Python test",
        round=0,
    )

    sim = PythonSimulator()
    res = sim.run_test(test=test, firmware_dir=fw_dir, run_dir=tmp_path)
    assert res.status == "PASS"


def test_orchestrator_with_virtual_mock_simulator(tmp_path):
    """Orchestrator runs full pipeline end-to-end with simulator_name='virtual_mock'."""
    dev_dir = tmp_path / "dev"
    dev_dir.mkdir(parents=True)
    fw_dir = tmp_path / "firmware"
    src_dir = fw_dir / "src"
    src_dir.mkdir(parents=True)
    (src_dir / "main.cpp").write_text("void setup() {}\nvoid loop() {}", encoding="utf-8")

    tests = [
        TestCase(
            id="T01",
            name="Test 1",
            category="normal",
            steps=[TestStep(set_temp=25.0)],
            expect=[Expectation(serial_contains="fan=OFF")],
            rationale="Normal",
            round=0,
        ),
        TestCase(
            id="T02",
            name="Test 2",
            category="normal",
            steps=[TestStep(set_temp=35.0)],
            expect=[Expectation(serial_contains="fan=ON")],
            rationale="Hot",
            round=0,
        ),
    ]

    import json
    (dev_dir / "tests.json").write_text(json.dumps({"tests": [t.model_dump() for t in tests]}))
    (dev_dir / "analysis.json").write_text(json.dumps({"summary": "test"}))

    manifest = run_all(
        run_id="mock_run_1",
        source_dir=dev_dir,
        firmware_dir=fw_dir,
        runs_base_dir=tmp_path / "runs",
        simulator_name="virtual_mock",
    )

    assert manifest.status == "done"
    assert manifest.total_tests == 2
    assert manifest.passed == 2
    assert manifest.failed == 0


def test_gazebo_simulator_registration():
    """Gazebo simulator is registered and available."""
    from agent.simulators.registry import get_simulator
    from agent.simulators.gazebo_sim import GazeboSimulator

    sim = get_simulator("gazebo")
    assert isinstance(sim, GazeboSimulator)
    avail, msg = sim.is_available()
    assert avail is True


def test_runner_auto_routes_python_away_from_wokwi(tmp_path):
    """When wokwi is selected on a Python firmware, runner auto-routes to python_sim."""
    from agent.runner import run_test

    fw_dir = tmp_path / "py_firmware"
    (fw_dir / "src").mkdir(parents=True)
    py_code = 'print("[DATA] temp=25.0 fan=OFF")\n'
    (fw_dir / "src" / "main.py").write_text(py_code, encoding="utf-8")

    test = TestCase(
        id="T01",
        name="Auto route test",
        category="normal",
        steps=[TestStep(set_temp=25.0)],
        expect=[Expectation(serial_contains="temp=25.0 fan=OFF")],
        rationale="Auto routing",
    )

    # Note: explicitly passing simulator_name="wokwi" to verify auto-routing away from wokwi
    res = run_test(
        test=test,
        firmware_dir=fw_dir,
        run_dir=tmp_path / "run",
        simulator_name="wokwi",
    )
    assert res.status == "PASS"
    assert res.exit_code == 0
    assert any("temp=25.0 fan=OFF" in line for line in res.observed_lines)
