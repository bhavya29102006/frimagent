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
    """Helper to build a valid suite of 14 test cases covering 7 categories with >= 4 boundary."""
    category_counts = {
        "boundary": 4,
        "normal": 2,
        "abnormal": 2,
        "sensor_failure": 1,
        "recovery": 1,
        "sequence": 2,
        "combination": 2,
    }
    tests: list[TestCase] = []
    idx = 1
    for cat, count in category_counts.items():
        for _ in range(count):
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


def test_generate_tests_topup_when_category_missing(tmp_path):
    """When generated tests miss a required category, a targeted top-up call is executed."""
    suite = _make_valid_test_suite()
    # Exclude recovery test -> 13 tests, missing recovery
    initial_tests = [t for t in suite if t.category != "recovery"]
    assert len(initial_tests) == 13
    assert not any(t.category == "recovery" for t in initial_tests)

    # Top-up response provides the missing recovery test
    topup_test = TestCase(
        id="T14",
        name="Recovery Test",
        category="recovery",
        steps=[TestStep(set_temp=65.0, wait_ms=2500), TestStep(set_temp=25.0, wait_ms=2500)],
        expect=[Expectation(serial_contains="fan=OFF", spec_ref="R3")],
        rationale="Recovery after heat",
        round=0,
    )

    mock_client = MagicMock()
    mock_resp1 = MagicMock()
    mock_resp1.text = TestList(tests=initial_tests).model_dump_json()

    mock_resp2 = MagicMock()
    mock_resp2.text = TestList(tests=[topup_test]).model_dump_json()

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
    assert any(t.category == "recovery" for t in result)
    assert mock_client.models.generate_content.call_count == 2

    # Check that topup prompt requested recovery
    topup_prompt = mock_client.models.generate_content.call_args_list[1].kwargs[
        "contents"
    ]
    assert "Missing categories requiring at least 1 test each: recovery" in topup_prompt


def test_generate_tests_topup_when_boundary_insufficient(tmp_path):
    """When boundary has fewer than 4 tests, top-up requests additional boundary tests."""
    suite = _make_valid_test_suite()
    # Keep only 2 boundary tests, but keep >= 12 tests
    boundary_seen = 0
    initial_tests = []
    for t in suite:
        if t.category == "boundary":
            boundary_seen += 1
            if boundary_seen <= 2:
                initial_tests.append(t)
        else:
            initial_tests.append(t)

    assert len(initial_tests) == 12
    assert sum(1 for t in initial_tests if t.category == "boundary") == 2

    # Topup returns 2 boundary tests with overlapping IDs to test unique ID merging
    topup_tests = [
        TestCase(
            id="T01",  # Colliding ID
            name="Extra Boundary 1",
            category="boundary",
            steps=[TestStep(set_temp=30.0, wait_ms=2500)],
            expect=[Expectation(serial_contains="fan=ON", spec_ref="R1")],
            rationale="Boundary 30.0",
            round=0,
        ),
        TestCase(
            id="T02",  # Colliding ID
            name="Extra Boundary 2",
            category="boundary",
            steps=[TestStep(set_temp=29.9, wait_ms=2500)],
            expect=[Expectation(serial_contains="fan=OFF", spec_ref="R3")],
            rationale="Boundary 29.9",
            round=0,
        ),
    ]

    mock_client = MagicMock()
    mock_resp1 = MagicMock()
    mock_resp1.text = TestList(tests=initial_tests).model_dump_json()

    mock_resp2 = MagicMock()
    mock_resp2.text = TestList(tests=topup_tests).model_dump_json()

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
    assert sum(1 for t in result if t.category == "boundary") == 4
    # All IDs must be unique
    all_ids = [t.id for t in result]
    assert len(all_ids) == len(set(all_ids))
    assert mock_client.models.generate_content.call_count == 2


def test_generate_tests_no_topup_when_already_covered(tmp_path):
    """When generated tests already meet all 7 categories and >= 4 boundary, no top-up is called."""
    valid_tests = _make_valid_test_suite()

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = TestList(tests=valid_tests).model_dump_json()
    mock_client.models.generate_content.return_value = mock_resp

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
    assert mock_client.models.generate_content.call_count == 1


