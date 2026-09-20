"""Unit tests for agent/coverage.py."""

import pytest
from agent.coverage import compute_coverage, REQUIRED_CATEGORIES
from agent.models import Expectation, TestCase, TestResult, TestStep


def _make_test(
    test_id: str,
    category: str,
    spec_ref: str | None = None,
) -> TestCase:
    return TestCase(
        id=test_id,
        name=f"Test {test_id}",
        category=category,
        sensor="disconnected" if category == "sensor_failure" else "normal",
        steps=[TestStep(set_temp=25.0, wait_ms=2500)],
        expect=[
            Expectation(
                serial_contains="fan=ON",
                spec_ref=spec_ref,
            )
        ],
        rationale="Testing scenario",
        round=0,
    )


def test_compute_coverage_all_categories_present_even_if_empty():
    """All 7 required categories must exist in coverage matrix even with empty test list."""
    cov = compute_coverage([])

    for cat in REQUIRED_CATEGORIES:
        assert cat in cov["categories"]
        assert cov["categories"][cat]["total"] == 0
        assert cov["categories"][cat]["passed"] == 0
        assert cov["categories"][cat]["failed"] == 0
        assert cov["categories"][cat]["errors"] == 0


def test_compute_coverage_without_results():
    """When results is None, totals are counted and statuses remain 0."""
    tests = [
        _make_test("T01", "normal", "R3"),
        _make_test("T02", "boundary", "R1"),
        _make_test("T03", "boundary", "R1"),
    ]
    cov = compute_coverage(tests, results=None)

    assert cov["normal"]["total"] == 1
    assert cov["normal"]["passed"] == 0
    assert cov["boundary"]["total"] == 2
    assert cov["boundary"]["passed"] == 0
    assert cov["sensor_failure"]["total"] == 0


def test_compute_coverage_with_results():
    """Statuses (PASS, FAIL, ERROR) are properly counted per category."""
    tests = [
        _make_test("T01", "normal", "R3"),
        _make_test("T02", "boundary", "R1"),
        _make_test("T03", "sensor_failure", "R5"),
    ]
    results = [
        TestResult(
            test_id="T01",
            status="PASS",
            expected=["fan=OFF"],
            observed_lines=["fan=OFF"],
            serial_log="",
        ),
        TestResult(
            test_id="T02",
            status="FAIL",
            expected=["fan=ON"],
            observed_lines=["fan=OFF"],
            serial_log="",
            missing_expected=["fan=ON"],
        ),
        TestResult(
            test_id="T03",
            status="ERROR",
            expected=["fan=ON"],
            observed_lines=[],
            serial_log="",
            error_message="Simulator timed out",
        ),
    ]

    cov = compute_coverage(tests, results)

    assert cov["normal"]["total"] == 1
    assert cov["normal"]["passed"] == 1
    assert cov["normal"]["failed"] == 0

    assert cov["boundary"]["total"] == 1
    assert cov["boundary"]["passed"] == 0
    assert cov["boundary"]["failed"] == 1

    assert cov["sensor_failure"]["total"] == 1
    assert cov["sensor_failure"]["errors"] == 1


def test_compute_coverage_rule_mapping_and_r6():
    """Rules R1..R5 are mapped to test IDs via spec_ref, and R6 is marked not testable in simulator."""
    tests = [
        _make_test("T01", "normal", "R3"),
        _make_test("T02", "boundary", "R1"),
        _make_test("T03", "sequence", "R2"),
        _make_test("T04", "abnormal", "R4"),
        _make_test("T05", "sensor_failure", "R5"),
        _make_test("T06", "combination", "R1, R4"),  # Multi-rule ref
    ]
    cov = compute_coverage(tests)

    rules = cov["rules"]
    assert "T02" in rules["R1"]
    assert "T06" in rules["R1"]
    assert "T03" in rules["R2"]
    assert "T01" in rules["R3"]
    assert "T04" in rules["R4"]
    assert "T06" in rules["R4"]
    assert "T05" in rules["R5"]
    assert rules["R6"] == "not testable in simulator"


def test_coverage_result_dict_access_compatibility():
    """CoverageResult supports both direct category lookup and cov['categories']."""
    tests = [_make_test("T01", "normal")]
    cov = compute_coverage(tests)

    assert "normal" in cov
    assert "categories" in cov
    assert "rules" in cov
    assert cov["normal"]["total"] == 1
    assert cov.get("normal")["total"] == 1
    assert cov["categories"]["normal"]["total"] == 1
