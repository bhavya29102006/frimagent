"""Smoke test for app/main.py helper functions and module imports."""

from pathlib import Path
import pytest

from agent.models import TestCase, TestStep
from app.main import format_steps_plain, get_available_runs


def test_format_steps_plain_normal():
    test = TestCase(
        id="T01",
        name="Normal Test",
        category="normal",
        steps=[TestStep(set_temp=25.0, wait_ms=2500), TestStep(set_temp=30.0)],
        expect=[],
        rationale="Step test",
    )
    res = format_steps_plain(test)
    assert res == "Set temp 25.0°C ➔ Set temp 30.0°C"


def test_format_steps_plain_disconnected():
    test = TestCase(
        id="T05",
        name="Disconnect Test",
        category="sensor_failure",
        sensor="disconnected",
        steps=[],
        expect=[],
        rationale="Disconnect test",
    )
    res = format_steps_plain(test)
    assert "Sensor wire disconnected" in res


def test_format_steps_plain_empty():
    test = TestCase(
        id="T06",
        name="Empty steps",
        category="normal",
        steps=[],
        expect=[],
        rationale="Empty",
    )
    assert format_steps_plain(test) == "No input change"


def test_get_available_runs():
    runs = get_available_runs()
    assert isinstance(runs, list)
    assert "cache" not in runs


def test_load_golden_fix_attempt():
    """Verify offline replay loads the golden fix attempt from runs/golden/fix/."""
    from agent.fixer import load_fix_attempt
    att = load_fix_attempt("golden")
    assert att is not None
    assert att.status == "validated"
    assert len(att.proposal.hunks) >= 1
    assert att.validation.ok is True
    assert att.after_counts is not None
    assert "T04" in att.fixed_tests or len(att.fixed_tests) > 0


def test_save_golden_fix_attempt(tmp_path):
    """Verify save_golden_fix_attempt exports attempt artifacts to golden/fix/."""
    from agent.fixer import save_golden_fix_attempt
    from agent.models import FixAttempt, PatchProposal, PatchValidation

    att = FixAttempt(
        attempt_id="att-test",
        status="validated",
        proposal=PatchProposal(hunks=[], summary="Dummy fix"),
        validation=PatchValidation(ok=True, checks=[]),
        before_counts={"total": 14, "passed": 11, "failed": 3, "errors": 0},
    )

    dest = save_golden_fix_attempt("test_run", att, runs_base_dir=tmp_path)
    assert dest.is_dir()
    assert (dest / "attempt.json").is_file()
    assert (dest / "proposal.json").is_file()
    assert (dest / "validation.json").is_file()


def test_classify_error():
    """Verify classify_error returns friendly cause and hint with no technical tracebacks."""
    from app.main import classify_error
    cause, hint = classify_error(Exception("429 RESOURCE_EXHAUSTED rate limit"))
    assert "429" in cause
    assert "quota" in hint.lower()

    cause_key, hint_key = classify_error(Exception("GEMINI_API_KEY invalid"))
    assert "Gemini API key" in cause_key


def test_log_ui_error(tmp_path):
    """Verify log_ui_error writes technical traceback to runs/<run_id>/error.log."""
    from app.main import log_ui_error
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.main.RUNS_DIR", tmp_path)
        try:
            raise ValueError("Test error message")
        except Exception as exc:
            log_path = log_ui_error("run_test", "test_action", exc)
            assert log_path.is_file()
            content = log_path.read_text(encoding="utf-8")
            assert "ValueError: Test error message" in content
            assert "Error during 'test_action'" in content


def test_get_available_firmwares():
    """Verify get_available_firmwares returns all firmware directories."""
    from app.main import get_available_firmwares
    fws = get_available_firmwares()
    assert "fan_controller" in fws
    assert "incubator_controller" in fws
    assert "smart_door_lock" in fws
    assert "water_tank_monitor" in fws
    assert "iot_weather_node" in fws
    assert "broken_syntax_demo" in fws


def test_find_firmware_src_file():
    """Verify find_firmware_src_file resolves correct source files for each language."""
    from app.main import FIRMWARE_BASE_DIR, find_firmware_src_file
    
    fan_src = find_firmware_src_file(FIRMWARE_BASE_DIR / "fan_controller")
    assert fan_src.name == "main.cpp"

    tank_src = find_firmware_src_file(FIRMWARE_BASE_DIR / "water_tank_monitor")
    assert tank_src.name == "main.c"

    weather_src = find_firmware_src_file(FIRMWARE_BASE_DIR / "iot_weather_node")
    assert weather_src.name == "main.py"

    broken_src = find_firmware_src_file(FIRMWARE_BASE_DIR / "broken_syntax_demo")
    assert broken_src.name == "main.cpp"


def test_get_local_sample_firmwares():
    """Verify get_local_sample_firmwares discovers all sample files in sample_firmwares/."""
    from app.main import get_local_sample_firmwares
    samples = get_local_sample_firmwares()
    assert "1_fan_controller.cpp" in samples
    assert "2_incubator_controller.cpp" in samples
    assert "3_smart_door_lock.cpp" in samples
    assert "4_water_tank_monitor.c" in samples
    assert "5_iot_weather_node.py" in samples
    assert "6_broken_syntax_demo.cpp" in samples


