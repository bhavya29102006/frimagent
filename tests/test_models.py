"""Tests for Pydantic data models in agent/models.py."""

import pytest
from pydantic import ValidationError

from agent.models import (
    Category,
    Expectation,
    Finding,
    FindingList,
    FirmwareAnalysis,
    RunManifest,
    SpecRule,
    TestCase,
    TestList,
    TestResult,
    TestStep,
)


def test_spec_rule_defaults_and_validation():
    """SpecRule initializes with correct defaults and validates confidence."""
    rule = SpecRule(id="R1", text="Fan is ON when temp >= 30.0")
    assert rule.id == "R1"
    assert rule.text == "Fan is ON when temp >= 30.0"
    assert rule.source_lines == []
    assert rule.confidence == "spec"

    # Inferred confidence
    rule_inferred = SpecRule(
        id="R2", text="Inferred rule", source_lines=[10, 11], confidence="inferred"
    )
    assert rule_inferred.confidence == "inferred"
    assert rule_inferred.source_lines == [10, 11]

    # Invalid confidence
    with pytest.raises(ValidationError):
        SpecRule(id="R3", text="Invalid", confidence="guessed")  # type: ignore


def test_firmware_analysis_serialization():
    """FirmwareAnalysis validates and serializes to/from JSON."""
    analysis = FirmwareAnalysis(
        summary="Fan controller firmware with DHT22 sensor and LED fan indicator.",
        inputs=["DHT22 temperature sensor on pin 2"],
        outputs=["Fan LED on pin 13", "Serial output at 9600 baud"],
        constants={"ON_THRESHOLD": "30.0", "HYSTERESIS": "2.0"},
        states=["IDLE", "RUNNING", "OVERHEAT"],
        error_handling=["Sensor NaN detection", "Fail-safe fan ON"],
        communication=["[INFO] BOOT", "[DATA] temp=<x.x> fan=<ON|OFF>"],
        spec_rules=[
            SpecRule(id="R1", text="Fan ON when temp >= 30.0", source_lines=[44])
        ],
        risk_areas=["Hysteresis logic", "Boundary condition at 30.0"],
    )

    json_str = analysis.model_dump_json()
    assert "DHT22 temperature sensor on pin 2" in json_str

    restored = FirmwareAnalysis.model_validate_json(json_str)
    assert restored.summary == analysis.summary
    assert len(restored.spec_rules) == 1
    assert restored.spec_rules[0].id == "R1"


def test_test_step_defaults():
    """TestStep defaults wait_ms to 2500 and set_temp to None."""
    step = TestStep()
    assert step.set_temp is None
    assert step.wait_ms == 2500

    step_custom = TestStep(set_temp=30.0, wait_ms=3000)
    assert step_custom.set_temp == 30.0
    assert step_custom.wait_ms == 3000


def test_expectation_validation():
    """Expectation requires serial_contains and allows optional spec_ref."""
    exp = Expectation(serial_contains="[DATA] temp=30.0 fan=ON", spec_ref="R1")
    assert exp.serial_contains == "[DATA] temp=30.0 fan=ON"
    assert exp.spec_ref == "R1"

    exp_no_ref = Expectation(serial_contains="[INFO] BOOT")
    assert exp_no_ref.spec_ref is None

    with pytest.raises(ValidationError):
        Expectation()  # type: ignore


def test_test_case_categories_and_validation():
    """TestCase enforces Category literal and expected fields."""
    valid_categories = [
        "normal",
        "boundary",
        "abnormal",
        "sensor_failure",
        "recovery",
        "sequence",
        "combination",
        "followup",
    ]

    for cat in valid_categories:
        tc = TestCase(
            id="T01",
            name="Test",
            category=cat,  # type: ignore
            steps=[TestStep(set_temp=25.0)],
            expect=[Expectation(serial_contains="fan=OFF")],
            rationale="Verify room temp behavior",
        )
        assert tc.category == cat
        assert tc.sensor == "normal"
        assert tc.round == 0
        assert tc.must_not == []

    # Invalid category
    with pytest.raises(ValidationError):
        TestCase(
            id="T99",
            name="Invalid",
            category="unsupported_category",  # type: ignore
            steps=[],
            expect=[Expectation(serial_contains="fan=OFF")],
            rationale="Test invalid category",
        )


def test_test_result_statuses():
    """TestResult allows only PASS, FAIL, or ERROR statuses."""
    res_pass = TestResult(
        test_id="T01",
        status="PASS",
        exit_code=0,
        expected=["[DATA] temp=25.0 fan=OFF"],
        observed_lines=["[DATA] temp=25.0 fan=OFF"],
        serial_log="[INFO] BOOT\n[DATA] temp=25.0 fan=OFF\n",
    )
    assert res_pass.status == "PASS"

    with pytest.raises(ValidationError):
        TestResult(
            test_id="T01",
            status="UNKNOWN",  # type: ignore
            expected=[],
            observed_lines=[],
            serial_log="",
        )


def test_finding_severities_and_structure():
    """Finding validates severity literals and stores suspect lines."""
    finding = Finding(
        id="FIND-1",
        title="Boundary temperature 30.0 does not turn fan ON",
        failed_tests=["T02"],
        spec_ref="R1",
        expected="fan=ON at 30.0",
        observed="fan=OFF at 30.0",
        likely_cause="Strict inequality > used instead of >=",
        suspect_lines=[44],
        suggested_fix="Change t > 30.0 to t >= 30.0",
        severity="high",
    )
    assert finding.id == "FIND-1"
    assert finding.severity == "high"

    with pytest.raises(ValidationError):
        Finding(
            id="FIND-2",
            title="Title",
            failed_tests=[],
            expected="A",
            observed="B",
            likely_cause="C",
            suspect_lines=[],
            suggested_fix="D",
            severity="critical",  # type: ignore
        )


def test_run_manifest_fields():
    """RunManifest tracks overall pipeline statistics and status."""
    manifest = RunManifest(
        run_id="20260920-153000",
        firmware_name="fan_controller",
        started_at="2026-09-20T15:30:00Z",
        status="running",
        total_tests=15,
        passed=12,
        failed=3,
        errors=0,
        followup_rounds=1,
    )
    assert manifest.status == "running"
    assert manifest.failed == 3

    manifest.status = "done"
    manifest.finished_at = "2026-09-20T15:33:00Z"
    assert manifest.status == "done"


def test_container_models():
    """TestList and FindingList serialize and validate lists correctly."""
    tc = TestCase(
        id="T01",
        name="Test",
        category="normal",
        steps=[TestStep(set_temp=25.0)],
        expect=[Expectation(serial_contains="fan=OFF")],
        rationale="Normal",
    )
    test_list = TestList(tests=[tc])
    assert len(test_list.tests) == 1

    finding = Finding(
        id="FIND-1",
        title="Test finding",
        failed_tests=["T01"],
        expected="A",
        observed="B",
        likely_cause="C",
        suspect_lines=[10],
        suggested_fix="Fix",
        severity="medium",
    )
    finding_list = FindingList(findings=[finding])
    assert len(finding_list.findings) == 1
