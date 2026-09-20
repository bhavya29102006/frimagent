"""Unit tests for agent/fixer.py."""

import json
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from agent.fixer import prepare_fix_workspace, run_autofix, verify_fix
from agent.models import (
    Expectation,
    Finding,
    FixAttempt,
    PatchHunk,
    PatchProposal,
    PatchValidation,
    TestCase,
    TestResult,
    TestStep,
)

SAMPLE_CPP = """/*
 * Fan Controller Spec Block
 */
#include <Arduino.h>

void setup() {
    pinMode(13, OUTPUT);
}

void loop() {
    float temp = 25.0;
    if (temp > 30.0) {
        digitalWrite(13, HIGH);
    }
}
"""


def _setup_test_environment(base_dir: Path, run_id: str = "run_01"):
    run_dir = base_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # 1. tests.json
    tests = [
        TestCase(
            id="T01",
            name="Boundary test at 30.0 C",
            category="boundary",
            steps=[TestStep(set_temp=30.0, wait_ms=2500)],
            expect=[Expectation(serial_contains="[FAN] ON", spec_ref="R1")],
            rationale="Boundary test at 30.0 C",
        ),
        TestCase(
            id="T02",
            name="Normal test at 25.0 C",
            category="normal",
            steps=[TestStep(set_temp=25.0, wait_ms=2500)],
            expect=[Expectation(serial_contains="[FAN] OFF", spec_ref="R2")],
            rationale="Normal test at 25.0 C",
        ),
    ]
    (run_dir / "tests.json").write_text(
        json.dumps([t.model_dump() for t in tests]), encoding="utf-8"
    )

    # 2. results.json (baseline: T01 FAIL, T02 PASS)
    results = [
        TestResult(
            test_id="T01",
            status="FAIL",
            expected=["[FAN] ON"],
            observed_lines=["[FAN] OFF"],
            serial_log="[FAN] OFF",
            missing_expected=["[FAN] ON"],
        ),
        TestResult(
            test_id="T02",
            status="PASS",
            expected=["[FAN] OFF"],
            observed_lines=["[FAN] OFF"],
            serial_log="[FAN] OFF",
        ),
    ]
    (run_dir / "results.json").write_text(
        json.dumps([r.model_dump() for r in results]), encoding="utf-8"
    )

    # 3. findings.json
    findings = [
        Finding(
            id="F01",
            title="Boundary comparison off by one",
            failed_tests=["T01"],
            expected="Fan ON at 30.0 C",
            observed="Fan OFF at 30.0 C",
            likely_cause="Strict > instead of >=",
            suspect_lines=[13],
            suggested_fix="Change > to >=",
            severity="high",
        )
    ]
    (run_dir / "findings.json").write_text(
        json.dumps([f.model_dump() for f in findings]), encoding="utf-8"
    )

    # 4. Dummy firmware source
    fw_dir = base_dir / "firmware" / "fan_controller"
    src_dir = fw_dir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "main.cpp").write_text(SAMPLE_CPP, encoding="utf-8")

    return run_dir, fw_dir


def test_prepare_fix_workspace(tmp_path):
    """prepare_fix_workspace copies firmware project including .pio directory."""
    fw_dir = tmp_path / "firmware"
    (fw_dir / "src").mkdir(parents=True)
    (fw_dir / "src" / "main.cpp").write_text("void setup() {}", encoding="utf-8")
    (fw_dir / ".pio" / "build").mkdir(parents=True)
    (fw_dir / ".pio" / "build" / "dummy.txt").write_text("build-cache", encoding="utf-8")

    project_copy = prepare_fix_workspace(
        run_id="run_test",
        attempt_id="att-01",
        firmware_dir=fw_dir,
        runs_base_dir=tmp_path / "runs",
    )

    assert project_copy.is_dir()
    assert (project_copy / "src" / "main.cpp").is_file()
    assert (project_copy / ".pio" / "build" / "dummy.txt").is_file()


def test_verify_fix_accepts_when_all_pass(tmp_path):
    """When fake runner returns PASS for fixed test and PASS for regression test, fix is validated."""
    run_dir, fw_dir = _setup_test_environment(tmp_path)
    run_id = run_dir.name

    hunk = PatchHunk(
        id="h1",
        start_line=13,
        end_line=13,
        original_code="    if (temp > 30.0) {",
        new_code="    if (temp >= 30.0) {",
        explanation="Fix threshold",
        confidence=0.9,
        fixes_tests=["T01"],
    )
    attempt = FixAttempt(
        attempt_id="att-pass",
        status="proposed",
        proposal=PatchProposal(hunks=[hunk], summary="Threshold fix"),
        validation=PatchValidation(ok=True, checks=[]),
        before_counts={"total": 2, "passed": 1, "failed": 1, "errors": 0},
    )

    # Prepare project copy
    copy_dir = tmp_path / run_id / "fix" / "att-pass" / "project"
    (copy_dir / "src").mkdir(parents=True)
    (copy_dir / "src" / "main.cpp").write_text(SAMPLE_CPP, encoding="utf-8")

    def fake_builder(path):
        return True, "Build OK", {}

    def fake_runner(test=None, test_case=None, **kwargs):
        # All tests pass now!
        t = test or test_case
        return TestResult(
            test_id=t.id,
            status="PASS",
            expected=[e.serial_contains for e in t.expect],
            observed_lines=["[FAN] ON"],
            serial_log="[FAN] ON",
        )

    result_attempt = verify_fix(
        attempt=attempt,
        run_id=run_id,
        runs_base_dir=tmp_path,
        runner_fn=fake_runner,
        builder_fn=fake_builder,
    )

    assert result_attempt.status == "validated"
    assert result_attempt.fixed_tests == ["T01"]
    assert result_attempt.regressions == []
    assert result_attempt.after_counts["passed"] == 2
    assert result_attempt.after_counts["failed"] == 0


def test_verify_fix_auto_rejects_on_regression(tmp_path):
    """When previously passing test fails on patched firmware, fix is auto-rejected."""
    run_dir, fw_dir = _setup_test_environment(tmp_path)
    run_id = run_dir.name

    hunk = PatchHunk(
        id="h1",
        start_line=13,
        end_line=13,
        original_code="    if (temp > 30.0) {",
        new_code="    if (temp >= 30.0) {",
        explanation="Fix threshold",
        confidence=0.9,
        fixes_tests=["T01"],
    )
    attempt = FixAttempt(
        attempt_id="att-regression",
        status="proposed",
        proposal=PatchProposal(hunks=[hunk], summary="Threshold fix"),
        validation=PatchValidation(ok=True, checks=[]),
        before_counts={"total": 2, "passed": 1, "failed": 1, "errors": 0},
    )

    copy_dir = tmp_path / run_id / "fix" / "att-regression" / "project"
    (copy_dir / "src").mkdir(parents=True)
    (copy_dir / "src" / "main.cpp").write_text(SAMPLE_CPP, encoding="utf-8")

    def fake_builder(path):
        return True, "Build OK", {}

    def fake_runner(test=None, test_case=None, **kwargs):
        # T01 passes, but T02 regresses to FAIL
        t = test or test_case
        if t.id == "T01":
            return TestResult(
                test_id=t.id,
                status="PASS",
                expected=[e.serial_contains for e in t.expect],
                observed_lines=["[FAN] ON"],
                serial_log="[FAN] ON",
            )
        else:
            return TestResult(
                test_id=t.id,
                status="FAIL",
                expected=[e.serial_contains for e in t.expect],
                observed_lines=["[FAN] ON"],
                serial_log="[FAN] ON",
                missing_expected=["[FAN] OFF"],
            )

    result_attempt = verify_fix(
        attempt=attempt,
        run_id=run_id,
        runs_base_dir=tmp_path,
        runner_fn=fake_runner,
        builder_fn=fake_builder,
    )

    assert result_attempt.status == "rejected"
    assert result_attempt.regressions == ["T02"]


def test_verify_fix_auto_rejects_on_zero_fixed(tmp_path):
    """When patch fails to fix any failed test, fix is auto-rejected."""
    run_dir, fw_dir = _setup_test_environment(tmp_path)
    run_id = run_dir.name

    hunk = PatchHunk(
        id="h1",
        start_line=13,
        end_line=13,
        original_code="    if (temp > 30.0) {",
        new_code="    if (temp >= 30.0) {",
        explanation="Fix threshold",
        confidence=0.9,
        fixes_tests=["T01"],
    )
    attempt = FixAttempt(
        attempt_id="att-zero-fixed",
        status="proposed",
        proposal=PatchProposal(hunks=[hunk], summary="Threshold fix"),
        validation=PatchValidation(ok=True, checks=[]),
        before_counts={"total": 2, "passed": 1, "failed": 1, "errors": 0},
    )

    copy_dir = tmp_path / run_id / "fix" / "att-zero-fixed" / "project"
    (copy_dir / "src").mkdir(parents=True)
    (copy_dir / "src" / "main.cpp").write_text(SAMPLE_CPP, encoding="utf-8")

    def fake_builder(path):
        return True, "Build OK", {}

    def fake_runner(test=None, test_case=None, **kwargs):
        # T01 still FAILS, T02 PASSES
        t = test or test_case
        status = "FAIL" if t.id == "T01" else "PASS"
        missing = ["[FAN] ON"] if status == "FAIL" else []
        return TestResult(
            test_id=t.id,
            status=status,
            expected=[e.serial_contains for e in t.expect],
            observed_lines=["[FAN] OFF"],
            serial_log="[FAN] OFF",
            missing_expected=missing,
        )

    result_attempt = verify_fix(
        attempt=attempt,
        run_id=run_id,
        runs_base_dir=tmp_path,
        runner_fn=fake_runner,
        builder_fn=fake_builder,
    )

    assert result_attempt.status == "rejected"
    assert len(result_attempt.fixed_tests) == 0
