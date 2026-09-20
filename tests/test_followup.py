"""Unit tests for agent/followup.py."""

from unittest.mock import MagicMock
import pytest

from agent.followup import _fallback_followup_tests, generate_followup_tests
from agent.models import (
    Expectation,
    FirmwareAnalysis,
    SpecRule,
    TestCase,
    TestList,
    TestResult,
    TestStep,
)


def _sample_analysis() -> FirmwareAnalysis:
    return FirmwareAnalysis(
        summary="Fan controller firmware",
        inputs=["DHT22 pin 2"],
        outputs=["Fan pin 13"],
        constants={"ON_THRESHOLD": "30.0"},
        states=["fanOn"],
        error_handling=["None"],
        communication=["9600"],
        spec_rules=[
            SpecRule(id="R1", text="Fan ON when temp >= 30.0 C", source_lines=[44])
        ],
        risk_areas=["Boundary"],
    )


def test_generate_followup_empty_when_no_failures():
    passed_results = [
        TestResult(
            test_id="T01",
            status="PASS",
            exit_code=0,
            duration_s=5.0,
            expected=["temp=25.0 fan=OFF"],
            observed_lines=["temp=25.0 fan=OFF"],
            serial_log="",
        )
    ]
    res = generate_followup_tests(
        failed_results=passed_results,
        test_cases=[],
        analysis=_sample_analysis(),
        numbered_source="1 | void setup() {}",
    )
    assert res == []


def test_generate_followup_with_mocked_llm(monkeypatch):
    failed_results = [
        TestResult(
            test_id="T03",
            status="FAIL",
            exit_code=42,
            duration_s=25.0,
            expected=["temp=30.0 fan=ON"],
            observed_lines=["temp=30.0 fan=OFF"],
            serial_log="",
        )
    ]
    test_cases = [
        TestCase(
            id="T03",
            name="Boundary test",
            category="boundary",
            steps=[TestStep(set_temp=30.0)],
            expect=[Expectation(serial_contains="temp=30.0 fan=ON")],
            rationale="Boundary check",
        )
    ]

    mock_llm_tests = [
        TestCase(
            id="T99",  # Will be sanitized to F01
            name="Probe 29.9 C",
            category="boundary",  # Will be overridden to followup
            steps=[TestStep(set_temp=29.9)],
            expect=[Expectation(serial_contains="temp=29.9 fan=OFF")],
            rationale="Probe",
        )
    ]

    monkeypatch.setattr(
        "agent.followup.generate_json",
        lambda *args, **kwargs: TestList(tests=mock_llm_tests),
    )

    followups = generate_followup_tests(
        failed_results=failed_results,
        test_cases=test_cases,
        analysis=_sample_analysis(),
        numbered_source="44 | else if (t > 30.0)",
        round_num=1,
    )

    assert len(followups) == 1
    assert followups[0].id == "F01"
    assert followups[0].category == "followup"
    assert followups[0].round == 1


def test_fallback_followup_boundary_and_hysteresis():
    failed_results = [
        TestResult(
            test_id="T03",
            status="FAIL",
            exit_code=42,
            duration_s=25.0,
            expected=["temp=30.0 fan=ON"],
            observed_lines=["temp=30.0 fan=OFF"],
            serial_log="",
        ),
        TestResult(
            test_id="T10",
            status="FAIL",
            exit_code=42,
            duration_s=25.0,
            expected=["temp=29.0 fan=ON"],
            observed_lines=["temp=29.0 fan=OFF"],
            serial_log="",
        ),
    ]
    test_cases = [
        TestCase(
            id="T03",
            name="Boundary 30.0",
            category="boundary",
            steps=[TestStep(set_temp=30.0)],
            expect=[Expectation(serial_contains="temp=30.0 fan=ON")],
            rationale="",
        ),
        TestCase(
            id="T10",
            name="Hysteresis 31 -> 29",
            category="sequence",
            steps=[TestStep(set_temp=31.0), TestStep(set_temp=29.0)],
            expect=[Expectation(serial_contains="temp=29.0 fan=ON")],
            rationale="",
        ),
    ]

    probes = _fallback_followup_tests(failed_results, test_cases, round_num=1)
    assert len(probes) >= 4
    for p in probes:
        assert p.id.startswith("F")
        assert p.category == "followup"
        assert p.round == 1

    # Check that 29.9 and 30.1 probes exist
    temps = [s.set_temp for p in probes for s in p.steps]
    assert 29.9 in temps
    assert 30.1 in temps
