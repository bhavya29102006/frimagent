"""Unit tests for agent/generator.py validation and retry logic."""

from unittest.mock import MagicMock
import pytest
from agent.generator import generate_tests, validate_test_cases
from agent.models import (
    Category,
    Expectation,
    FirmwareAnalysis,
    TestCase,
    TestList,
    TestStep,
)


def _make_valid_test_suite() -> list[TestCase]:
    """Helper to build a valid suite of 14 test cases covering 7 categories."""
    categories: list[Category] = [
        "normal",
        "boundary",
        "abnormal",
        "sensor_failure",
        "recovery",
        "sequence",
        "combination",
    ]
    tests: list[TestCase] = []
    # 2 tests per category = 14 tests
    idx = 1
    for cat in categories:
        for _ in range(2):
            tests.append(
                TestCase(
                    id=f"T{idx:02d}",
                    name=f"Test {idx}",
                    category=cat,
                    sensor="disconnected" if cat == "sensor_failure" else "normal",
                    steps=[TestStep(set_temp=25.0 + idx, wait_ms=2500)],
                    expect=[Expectation(serial_contains="fan=ON")],
                    rationale="Testing scenario",
                    round=0,
                )
            )
            idx += 1
    return tests


def test_validation_passes_on_valid_suite():
    """Valid test suite with 14 tests across 7 categories passes without errors."""
    tests = _make_valid_test_suite()
    errors = validate_test_cases(tests)
    assert errors == []


def test_validation_fails_on_too_few_tests():
    """Suite with fewer than 12 tests fails validation."""
    tests = _make_valid_test_suite()[:10]  # Only 10 tests
    errors = validate_test_cases(tests)
    assert any("at least 12 tests" in e for e in errors)


def test_validation_fails_on_duplicate_ids():
    """Suite with duplicate test IDs fails validation."""
    tests = _make_valid_test_suite()
    tests[1].id = tests[0].id  # Duplicate ID T01
    errors = validate_test_cases(tests)
    assert any("Duplicate test IDs" in e for e in errors)


def test_validation_fails_on_too_few_categories():
    """Suite with fewer than 6 categories fails validation."""
    tests = _make_valid_test_suite()
    # Collapse all categories to 'normal'
    for t in tests:
        t.category = "normal"
    errors = validate_test_cases(tests)
    assert any("at least 6 categories" in e for e in errors)


def test_validation_fails_on_temp_out_of_range():
    """Temperature outside [-40.0, 80.0] fails validation."""
    tests = _make_valid_test_suite()
    tests[0].steps[0].set_temp = 85.0
    tests[1].steps[0].set_temp = -45.0
    errors = validate_test_cases(tests)
    assert any("outside DHT22 range" in e for e in errors)


def test_validation_fails_on_too_many_steps():
    """More than 6 steps per test fails validation."""
    tests = _make_valid_test_suite()
    tests[0].steps = [TestStep(set_temp=25.0) for _ in range(7)]
    errors = validate_test_cases(tests)
    assert any("max 6 allowed" in e for e in errors)


def test_generate_tests_retries_on_validation_failure(tmp_path):
    """When first generation fails validation, generate_tests retries once with feedback."""
    invalid_tests = _make_valid_test_suite()[:5]  # Only 5 tests -> invalid
    valid_tests = _make_valid_test_suite()

    mock_client = MagicMock()
    mock_resp1 = MagicMock()
    mock_resp1.text = TestList(tests=invalid_tests).model_dump_json()

    mock_resp2 = MagicMock()
    mock_resp2.text = TestList(tests=valid_tests).model_dump_json()

    mock_client.models.generate_content.side_effect = [mock_resp1, mock_resp2]

    analysis = FirmwareAnalysis(
        summary="Test analysis",
        inputs=["pin 2"],
        outputs=["pin 13"],
        constants={},
        states=[],
        error_handling=[],
        communication=[],
        spec_rules=[],
        risk_areas=[],
    )

    result = generate_tests(
        analysis=analysis,
        source_code="void setup() {}",
        client=mock_client,
        model="gemini-test",
        cache_dir=tmp_path,
        use_cache=False,
    )

    assert len(result) == 14
    assert mock_client.models.generate_content.call_count == 2

    # Check that retry prompt received the validation errors
    retry_prompt = mock_client.models.generate_content.call_args_list[1].kwargs[
        "contents"
    ]
    assert "VALIDATION ERRORS" in retry_prompt
    assert "at least 12 tests" in retry_prompt
