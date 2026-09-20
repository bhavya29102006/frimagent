"""Unit tests for agent/evaluator.py."""

import pytest
from agent.evaluator import (
    collapse_firmware_lines,
    evaluate,
    extract_firmware_lines,
    strip_ansi,
)
from agent.models import Expectation, TestCase, TestStep


def _make_test(
    test_id: str = "T01",
    expected: list[str] | None = None,
    must_not: list[str] | None = None,
) -> TestCase:
    if expected is None:
        expected = ["temp=30.0 fan=OFF"]
    return TestCase(
        id=test_id,
        name="Sample Test",
        category="normal",
        steps=[TestStep(set_temp=30.0)],
        expect=[Expectation(serial_contains=s) for s in expected],
        must_not=must_not or [],
        rationale="Unit test verification",
    )


def test_extract_firmware_lines():
    raw_log = """
    Wokwi CLI v0.15.0
    Connecting to simulator...
    Connected to localhost:4000
    Starting simulation...
    \x1b[32m[INFO] BOOT\x1b[0m
    [fan_controller] Expected text matched: [INFO] BOOT
    [DATA] temp=25.0 fan=OFF
    [ALARM] OVERHEAT
    [ERROR] SENSOR_TIMEOUT
    Scenario completed successfully
    Timeout: simulation did not finish in 20000ms
    """
    lines = extract_firmware_lines(raw_log)
    assert lines == [
        "[INFO] BOOT",
        "[DATA] temp=25.0 fan=OFF",
        "[ALARM] OVERHEAT",
        "[ERROR] SENSOR_TIMEOUT",
    ]


def test_collapse_firmware_lines_empty():
    assert collapse_firmware_lines([]) == []


def test_collapse_firmware_lines_consecutive_and_tags():
    firmware_lines = [
        "[INFO] BOOT",
        "[DATA] temp=30.0 fan=OFF",
        "[DATA] temp=30.0 fan=OFF",
        "[DATA] temp=30.0 fan=OFF",
        "[DATA] temp=31.0 fan=ON",
        "[ALARM] OVERHEAT",
        "[ALARM] OVERHEAT",
        "[DATA] temp=25.0 fan=OFF",
    ]
    collapsed = collapse_firmware_lines(firmware_lines)
    assert collapsed == [
        "[INFO] BOOT",
        "temp=30.0 fan=OFF (x3)",
        "temp=31.0 fan=ON",
        "[ALARM] OVERHEAT (x2)",
        "temp=25.0 fan=OFF",
    ]


def test_evaluate_pass():
    test = _make_test(expected=["temp=25.0 fan=OFF"])
    raw_output = (
        "[INFO] BOOT\n"
        "[DATA] temp=25.0 fan=OFF\n"
        "Scenario completed successfully"
    )
    result = evaluate(test, raw_output, exit_code=0, duration_s=12.5)

    assert result.status == "PASS"
    assert result.exit_code == 0
    assert result.duration_s == 12.5
    assert result.violated_must_not == []
    assert result.missing_expected == []
    assert result.error_message is None
    assert "temp=25.0 fan=OFF" in result.observed_lines


def test_evaluate_fail_exit_42():
    test = _make_test(expected=["temp=31.0 fan=ON"])
    raw_output = (
        "[INFO] BOOT\n"
        "[DATA] temp=30.0 fan=OFF\n"
        "Timeout: simulation did not finish in 20000ms"
    )
    result = evaluate(test, raw_output, exit_code=42, duration_s=25.0)

    assert result.status == "FAIL"
    assert result.exit_code == 42
    assert "Simulation timed out" in (result.error_message or "")
    assert "temp=31.0 fan=ON" in result.missing_expected


def test_evaluate_must_not_fail():
    test = _make_test(
        expected=["temp=30.0 fan=OFF"],
        must_not=["fan=ON", "OVERHEAT"],
    )
    raw_output = (
        "[INFO] BOOT\n"
        "[DATA] temp=30.0 fan=OFF\n"
        "[DATA] temp=30.0 fan=ON\n"
        "Scenario completed successfully"
    )
    result = evaluate(test, raw_output, exit_code=0, duration_s=10.0)

    assert result.status == "FAIL"
    assert result.exit_code == 0
    assert result.violated_must_not == ["fan=ON"]
    assert "Violated forbidden must_not" in (result.error_message or "")


def test_evaluate_must_not_in_simulator_noise_not_flagged():
    """must_not strings appearing only in simulator harness lines are ignored."""
    test = _make_test(
        expected=["temp=30.0 fan=OFF"],
        must_not=["ERROR"],
    )
    raw_output = (
        "[INFO] BOOT\n"
        "[DATA] temp=30.0 fan=OFF\n"
        "ERROR: simulator helper message outside firmware\n"
        "Scenario completed successfully"
    )
    # The helper message does not start with [ERROR], so it is not in firmware_lines
    result = evaluate(test, raw_output, exit_code=0)
    assert result.status == "PASS"
    assert result.violated_must_not == []


def test_evaluate_exit_1_error():
    test = _make_test()
    raw_output = "Fatal simulator error: out of memory"
    result = evaluate(test, raw_output, exit_code=1, duration_s=1.2)

    assert result.status == "ERROR"
    assert result.exit_code == 1
    assert "exit code 1" in (result.error_message or "")


def test_evaluate_safety_check_error():
    """Exit 0 but NONE of expected strings appear in firmware lines yields ERROR."""
    test = _make_test(expected=["temp=35.0 fan=ON", "ALARM"])
    raw_output = (
        "[INFO] BOOT\n"
        "[DATA] temp=20.0 fan=OFF\n"
        "Scenario completed successfully"
    )
    result = evaluate(test, raw_output, exit_code=0)

    assert result.status == "ERROR"
    assert (
        result.error_message
        == "inconsistent: exit 0 but expected text not seen in firmware output"
    )
