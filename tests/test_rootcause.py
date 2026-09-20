"""Unit tests for agent/rootcause.py."""

import json
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from agent.models import (
    Expectation,
    Finding,
    FindingList,
    FirmwareAnalysis,
    SpecRule,
    TestCase,
    TestResult,
    TestStep,
)
from agent.rootcause import (
    analyze_root_causes,
    number_source_code,
    run_root_cause,
    summarize_failed_tests,
    summarize_spec_rules,
)


def _sample_analysis() -> FirmwareAnalysis:
    return FirmwareAnalysis(
        summary="Fan controller firmware",
        inputs=["DHT22 pin 2"],
        outputs=["Fan pin 13"],
        constants={"ON_THRESHOLD": "30.0"},
        states=["fanOn = true", "fanOn = false"],
        error_handling=["Spec requires sensor fail detection"],
        communication=["9600 baud"],
        spec_rules=[
            SpecRule(
                id="R1",
                text="Fan is ON when temperature >= 30.0 C.",
                source_lines=[44, 45],
            ),
            SpecRule(
                id="R2",
                text="Once ON, fan turns OFF only when <= 28.0 C.",
                source_lines=[46, 47],
            ),
            SpecRule(
                id="R5",
                text="Sensor failure prints [ERROR] SENSOR_FAIL.",
                source_lines=[],
            ),
        ],
        risk_areas=["Boundary check strictly > 30.0"],
    )


def _sample_tests() -> list[TestCase]:
    return [
        TestCase(
            id="T01",
            name="Normal Low",
            category="normal",
            steps=[TestStep(set_temp=25.0)],
            expect=[
                Expectation(serial_contains="temp=25.0 fan=OFF", spec_ref="R3")
            ],
            rationale="Verify fan OFF",
        ),
        TestCase(
            id="T03",
            name="Boundary Exact Threshold",
            category="boundary",
            steps=[TestStep(set_temp=30.0)],
            expect=[
                Expectation(serial_contains="temp=30.0 fan=ON", spec_ref="R1")
            ],
            rationale="Verify fan ON at boundary",
        ),
    ]


def test_number_source_code():
    code = "void setup() {\n  Serial.begin(9600);\n}"
    numbered = number_source_code(code)
    assert "  1 | void setup() {" in numbered
    assert "  2 |   Serial.begin(9600);" in numbered


def test_summarize_spec_rules():
    analysis = _sample_analysis()
    summary = summarize_spec_rules(analysis.spec_rules)
    assert "R1: Fan is ON when temperature >= 30.0 C." in summary
    assert "source lines: [44, 45]" in summary


def test_summarize_failed_tests():
    tests = _sample_tests()
    failed_results = [
        TestResult(
            test_id="T03",
            status="FAIL",
            exit_code=42,
            duration_s=25.0,
            expected=["temp=30.0 fan=ON"],
            observed_lines=["temp=30.0 fan=OFF"],
            serial_log="Timeout log",
            violated_must_not=[],
            missing_expected=["temp=30.0 fan=ON"],
        )
    ]
    summary = summarize_failed_tests(failed_results, tests)
    assert "Test ID: T03" in summary
    assert "Category: boundary" in summary
    assert "temp=30.0 fan=ON" in summary


def test_analyze_root_causes_empty_when_no_failures():
    """Returns empty list immediately when all tests passed."""
    tests = _sample_tests()
    analysis = _sample_analysis()
    passed_results = [
        TestResult(
            test_id="T01",
            status="PASS",
            exit_code=0,
            duration_s=12.0,
            expected=["temp=25.0 fan=OFF"],
            observed_lines=["temp=25.0 fan=OFF"],
            serial_log="All good",
        )
    ]
    findings = analyze_root_causes(
        failed_results=passed_results,
        test_cases=tests,
        analysis=analysis,
        numbered_source="1 | void loop() {}",
    )
    assert findings == []


def test_analyze_root_causes_with_llm(monkeypatch):
    tests = _sample_tests()
    analysis = _sample_analysis()
    failed_results = [
        TestResult(
            test_id="T03",
            status="FAIL",
            exit_code=42,
            duration_s=25.0,
            expected=["temp=30.0 fan=ON"],
            observed_lines=["temp=30.0 fan=OFF"],
            serial_log="Timeout log",
            violated_must_not=[],
            missing_expected=["temp=30.0 fan=ON"],
        )
    ]

    mock_findings = [
        Finding(
            id="FIND-1",
            title="Strict inequality used on threshold",
            failed_tests=["T03"],
            spec_ref="R1",
            expected="Fan turns ON at >= 30.0 C",
            observed="Fan remained OFF at exactly 30.0 C",
            likely_cause="Code checks `t > 30.0` instead of `t >= 30.0`.",
            suspect_lines=[44],
            suggested_fix="Change `if (t > 30.0)` to `if (t >= 30.0)`.",
            severity="medium",
        )
    ]

    monkeypatch.setattr(
        "agent.rootcause.generate_json",
        lambda *args, **kwargs: FindingList(findings=mock_findings),
    )

    findings = analyze_root_causes(
        failed_results=failed_results,
        test_cases=tests,
        analysis=analysis,
        numbered_source="44 | else if (t > 30.0) { fanOn = true; }",
    )
    assert len(findings) == 1
    assert findings[0].id == "FIND-1"
    assert findings[0].spec_ref == "R1"
    assert findings[0].suspect_lines == [44]


def test_analyze_root_causes_fallback_on_error(monkeypatch):
    """When LLM call fails, fallback generates valid findings."""
    tests = _sample_tests()
    analysis = _sample_analysis()
    failed_results = [
        TestResult(
            test_id="T03",
            status="FAIL",
            exit_code=42,
            duration_s=25.0,
            expected=["temp=30.0 fan=ON"],
            observed_lines=["temp=30.0 fan=OFF"],
            serial_log="Timeout log",
            violated_must_not=[],
            missing_expected=["temp=30.0 fan=ON"],
        )
    ]

    def raise_err(*args, **kwargs):
        raise RuntimeError("LLM rate limit / network error")

    monkeypatch.setattr("agent.rootcause.generate_json", raise_err)

    findings = analyze_root_causes(
        failed_results=failed_results,
        test_cases=tests,
        analysis=analysis,
        numbered_source="44 | else if (t > 30.0)",
    )
    assert len(findings) == 1
    assert findings[0].id == "FIND-1"
    assert findings[0].spec_ref == "R1"
    assert "T03" in findings[0].failed_tests


def test_run_root_cause_disk_cycle(tmp_path: Path, monkeypatch):
    run_dir = tmp_path / "run_test"
    run_dir.mkdir()

    analysis = _sample_analysis()
    tests = _sample_tests()
    failed_results = [
        TestResult(
            test_id="T03",
            status="FAIL",
            exit_code=42,
            duration_s=25.0,
            expected=["temp=30.0 fan=ON"],
            observed_lines=["temp=30.0 fan=OFF"],
            serial_log="Timeout log",
        )
    ]

    (run_dir / "analysis.json").write_text(
        analysis.model_dump_json(), encoding="utf-8"
    )
    (run_dir / "tests.json").write_text(
        json.dumps({"tests": [t.model_dump() for t in tests]}), encoding="utf-8"
    )
    (run_dir / "results.json").write_text(
        json.dumps([r.model_dump() for r in failed_results]), encoding="utf-8"
    )

    mock_findings = [
        Finding(
            id="FIND-1",
            title="Threshold bug",
            failed_tests=["T03"],
            spec_ref="R1",
            expected="ON at 30",
            observed="OFF at 30",
            likely_cause="Strict greater than",
            suspect_lines=[44],
            suggested_fix="t >= 30.0",
            severity="medium",
        )
    ]

    monkeypatch.setattr(
        "agent.rootcause.generate_json",
        lambda *args, **kwargs: FindingList(findings=mock_findings),
    )

    findings = run_root_cause(run_dir=run_dir)
    assert len(findings) == 1
    assert (run_dir / "findings.json").is_file()

    saved_data = json.loads(
        (run_dir / "findings.json").read_text(encoding="utf-8")
    )
    assert len(saved_data) == 1
    assert saved_data[0]["id"] == "FIND-1"
