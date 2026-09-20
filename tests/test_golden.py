"""Unit tests for runs/golden/ offline replay dataset (TASK-017)."""

import json
from pathlib import Path
import pytest

from agent.models import (
    Finding,
    FirmwareAnalysis,
    RunManifest,
    TestCase,
    TestResult,
)

GOLDEN_DIR = Path("runs/golden")


def test_golden_directory_exists():
    """Verify that runs/golden exists and contains required artifacts."""
    assert GOLDEN_DIR.is_dir()
    required_files = [
        "manifest.json",
        "analysis.json",
        "tests.json",
        "results.json",
        "findings.json",
        "report.html",
        "report.md",
        "firmware_source.txt",
    ]
    for rf in required_files:
        p = GOLDEN_DIR / rf
        assert p.is_file(), f"Missing required golden artifact: {rf}"


def test_golden_models_validate():
    """Verify all golden JSON artifacts conform to their Pydantic models."""
    manifest = RunManifest.model_validate_json(
        (GOLDEN_DIR / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest.run_id == "golden"
    assert manifest.status == "done"
    assert manifest.total_tests == 14
    assert manifest.passed == 11
    assert manifest.failed == 3
    assert manifest.errors == 0

    analysis = FirmwareAnalysis.model_validate_json(
        (GOLDEN_DIR / "analysis.json").read_text(encoding="utf-8")
    )
    assert len(analysis.spec_rules) >= 6

    tests_raw = json.loads(
        (GOLDEN_DIR / "tests.json").read_text(encoding="utf-8")
    )
    test_list = (
        tests_raw.get("tests", [])
        if isinstance(tests_raw, dict)
        else tests_raw
    )
    tests = [TestCase.model_validate(t) for t in test_list]
    assert len(tests) == 14

    results_raw = json.loads(
        (GOLDEN_DIR / "results.json").read_text(encoding="utf-8")
    )
    results = [TestResult.model_validate(r) for r in results_raw]
    assert len(results) == 14

    findings_raw = json.loads(
        (GOLDEN_DIR / "findings.json").read_text(encoding="utf-8")
    )
    findings = [Finding.model_validate(f) for f in findings_raw]
    assert len(findings) == 3

    # Check that findings reference R1 (B1), R5 (B3), R2 (B2)
    spec_refs = {f.spec_ref for f in findings if f.spec_ref}
    assert "R1" in spec_refs
    assert "R2" in spec_refs
    assert "R5" in spec_refs
