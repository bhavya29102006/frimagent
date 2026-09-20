"""Unit tests for agent/reporter.py."""

import json
from pathlib import Path
import pytest

from agent.models import (
    Expectation,
    Finding,
    FirmwareAnalysis,
    RunManifest,
    SpecRule,
    TestCase,
    TestResult,
    TestStep,
)
from agent.reporter import (
    _compute_coverage,
    _extract_source_snippet,
    build_html_report,
    build_markdown_report,
    generate_reports,
)


def _fixture_manifest() -> RunManifest:
    return RunManifest(
        run_id="20260920-190000",
        firmware_name="fan_controller",
        started_at="2026-09-20T19:00:00Z",
        finished_at="2026-09-20T19:05:00Z",
        status="done",
        total_tests=3,
        passed=1,
        failed=1,
        errors=1,
    )


def _fixture_tests() -> list[TestCase]:
    return [
        TestCase(
            id="T01",
            name="Normal Low Temp",
            category="normal",
            steps=[TestStep(set_temp=25.0)],
            expect=[
                Expectation(serial_contains="temp=25.0 fan=OFF", spec_ref="R3")
            ],
            rationale="Verify room temp",
        ),
        TestCase(
            id="T03",
            name="Boundary Exact Threshold",
            category="boundary",
            steps=[TestStep(set_temp=30.0)],
            expect=[
                Expectation(serial_contains="temp=30.0 fan=ON", spec_ref="R1")
            ],
            rationale="Verify boundary",
        ),
        TestCase(
            id="T05",
            name="Sensor Disconnect",
            category="sensor_failure",
            steps=[TestStep(set_temp=25.0)],
            expect=[
                Expectation(
                    serial_contains="[ERROR] SENSOR_FAIL", spec_ref="R5"
                )
            ],
            rationale="Verify fail-safe",
        ),
    ]


def _fixture_results() -> list[TestResult]:
    return [
        TestResult(
            test_id="T01",
            status="PASS",
            exit_code=0,
            duration_s=12.2,
            expected=["temp=25.0 fan=OFF"],
            observed_lines=["temp=25.0 fan=OFF"],
            serial_log="PASS",
        ),
        TestResult(
            test_id="T03",
            status="FAIL",
            exit_code=42,
            duration_s=25.0,
            expected=["temp=30.0 fan=ON"],
            observed_lines=["temp=30.0 fan=OFF"],
            serial_log="FAIL",
            missing_expected=["temp=30.0 fan=ON"],
        ),
        TestResult(
            test_id="T05",
            status="ERROR",
            exit_code=1,
            duration_s=1.0,
            expected=["[ERROR] SENSOR_FAIL"],
            observed_lines=[],
            serial_log="CRASH",
            error_message="Simulator fault",
        ),
    ]


def _fixture_findings() -> list[Finding]:
    return [
        Finding(
            id="FIND-1",
            title="Threshold inequality bug",
            failed_tests=["T03"],
            spec_ref="R1",
            expected="Fan turns ON at >= 30.0 C",
            observed="Fan stayed OFF at 30.0 C",
            likely_cause="Code checks strict greater than `t > 30.0`.",
            suspect_lines=[44],
            suggested_fix="Change `t > 30.0` to `t >= 30.0`.",
            severity="medium",
        )
    ]


def _fixture_analysis() -> FirmwareAnalysis:
    return FirmwareAnalysis(
        summary="Fan controller firmware",
        inputs=["DHT22 on pin 2"],
        outputs=["Fan on pin 13"],
        constants={"ON_THRESHOLD": "30.0"},
        states=["fanOn"],
        error_handling=["None"],
        communication=["9600"],
        spec_rules=[
            SpecRule(
                id="R1",
                text="Fan is ON when temp >= 30.0 C",
                source_lines=[44, 45],
            )
        ],
        risk_areas=["Boundary check"],
    )


def test_compute_coverage():
    tests = _fixture_tests()
    results = _fixture_results()
    cov = _compute_coverage(tests, results)

    assert "normal" in cov
    assert cov["normal"]["total"] == 1
    assert cov["normal"]["passed"] == 1

    assert "boundary" in cov
    assert cov["boundary"]["failed"] == 1

    assert "sensor_failure" in cov
    assert cov["sensor_failure"]["errors"] == 1


def test_extract_source_snippet():
    code = "\n".join(f"line {i}" for i in range(1, 50))
    snippet = _extract_source_snippet(code, [44])
    assert ">>  44 | line 44" in snippet
    assert "    42 | line 42" in snippet
    assert "    46 | line 46" in snippet


def test_build_markdown_report():
    manifest = _fixture_manifest()
    tests = _fixture_tests()
    results = _fixture_results()
    findings = _fixture_findings()
    analysis = _fixture_analysis()

    md = build_markdown_report(
        manifest,
        tests,
        results,
        findings,
        analysis,
        source_code="void setup() {}",
    )

    assert "# FirmAgent Autonomous Test Report" in md
    assert "20260920-190000" in md
    assert "## Executive Summary" in md
    assert "## Test Coverage Matrix" in md
    assert "## Root-Cause Findings & Planted Bugs" in md
    assert "[FIND-1] Threshold inequality bug" in md
    assert "## Test Execution Details" in md
    assert "T01" in md
    assert "T03" in md


def test_build_html_report_offline_and_styling():
    manifest = _fixture_manifest()
    tests = _fixture_tests()
    results = _fixture_results()
    findings = _fixture_findings()
    analysis = _fixture_analysis()

    html_out = build_html_report(
        manifest,
        tests,
        results,
        findings,
        analysis,
        source_code="void setup() {}",
    )

    # Must be complete HTML5
    assert "<!DOCTYPE html>" in html_out
    assert "</html>" in html_out
    # Theme colors present
    assert "#0F172A" in html_out
    assert "#1E293B" in html_out
    # Content present
    assert "20260920-190000" in html_out
    assert "FIND-1" in html_out
    assert "T03" in html_out
    assert "Threshold inequality bug" in html_out
    # No external http or script tags (100% offline)
    assert "http://" not in html_out
    assert "https://" not in html_out
    assert "<script" not in html_out


def test_generate_reports_writes_files(tmp_path: Path):
    run_dir = tmp_path / "run_report_test"
    run_dir.mkdir()

    manifest = _fixture_manifest()
    tests = _fixture_tests()
    results = _fixture_results()
    findings = _fixture_findings()
    analysis = _fixture_analysis()

    (run_dir / "manifest.json").write_text(
        manifest.model_dump_json(), encoding="utf-8"
    )
    (run_dir / "tests.json").write_text(
        json.dumps({"tests": [t.model_dump() for t in tests]}), encoding="utf-8"
    )
    (run_dir / "results.json").write_text(
        json.dumps([r.model_dump() for r in results]), encoding="utf-8"
    )
    (run_dir / "findings.json").write_text(
        json.dumps([f.model_dump() for f in findings]), encoding="utf-8"
    )
    (run_dir / "analysis.json").write_text(
        analysis.model_dump_json(), encoding="utf-8"
    )

    md_path, html_path = generate_reports(run_dir)

    assert md_path.is_file()
    assert html_path.is_file()
    assert md_path.name == "report.md"
    assert html_path.name == "report.html"

    md_text = md_path.read_text(encoding="utf-8")
    assert "FIND-1" in md_text

    html_text = html_path.read_text(encoding="utf-8")
    assert "FIND-1" in html_text
