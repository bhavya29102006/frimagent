"""Test generator module: analysis + source -> TestCase list."""

from collections import Counter
from pathlib import Path
from google import genai
from agent.analyzer import add_line_numbers
from agent.coverage import REQUIRED_CATEGORIES
from agent.llm import generate_json
from agent.models import FirmwareAnalysis, TestCase, TestList
from agent.prompts import (
    make_generator_prompt,
    make_generator_repair_prompt,
    make_generator_topup_prompt,
)


def validate_test_cases(
    tests: list[TestCase], max_tests: int = 20
) -> list[str]:
    """Validate a list of TestCase objects against requirements.

    Returns:
        list[str]: List of validation error messages, empty if valid.
    """
    errors: list[str] = []

    # 1. Count: 12 to max_tests
    if len(tests) < 12:
        errors.append(f"Expected at least 12 tests, got {len(tests)}")
    elif len(tests) > max_tests:
        errors.append(f"Expected at most {max_tests} tests, got {len(tests)}")

    # 2. Unique IDs (T01, T02...)
    ids = [t.id for t in tests]
    if len(ids) != len(set(ids)):
        duplicates = sorted({x for x in ids if ids.count(x) > 1})
        errors.append(f"Duplicate test IDs found: {duplicates}")

    # 3. Category diversity: at least 6 categories
    categories = {t.category for t in tests}
    if len(categories) < 6:
        errors.append(
            f"Expected at least 6 categories, found {len(categories)}: {sorted(categories)}"
        )

    # 4. Per-test step constraints and valid DHT22 sensor range [-40.0, 80.0]
    for t in tests:
        if len(t.steps) > 6:
            errors.append(f"Test {t.id} has {len(t.steps)} steps (max 6 allowed)")
        if not t.expect:
            errors.append(f"Test {t.id} has no expectations")

        for s_idx, step in enumerate(t.steps):
            if step.set_temp is not None:
                if step.set_temp < -40.0 or step.set_temp > 80.0:
                    errors.append(
                        f"Test {t.id} step {s_idx + 1} temperature {step.set_temp} outside DHT22 range [-40.0, 80.0]"
                    )
            if step.wait_ms < 500 or step.wait_ms > 10000:
                errors.append(
                    f"Test {t.id} step {s_idx + 1} wait_ms {step.wait_ms} outside range [500, 10000]"
                )

    return errors


def generate_tests(
    analysis: FirmwareAnalysis,
    source_code: str,
    client: genai.Client | None = None,
    model: str | None = None,
    use_cache: bool = True,
    cache_dir: Path | None = None,
) -> list[TestCase]:
    """Generate and validate 12 to 20 test cases from FirmwareAnalysis and source code.

    Enforces:
    - 12 to 20 tests covering at least 6 categories initially.
    - Coverage check ensuring every required category (normal, boundary, abnormal,
      sensor_failure, recovery, sequence, combination) has >= 1 test and boundary has >= 4.
    - Makes ONE targeted top-up call if any required category or boundary count is missing.
    - Expected values from SPEC, not current code implementation.
    - Temperature range [-40.0, 80.0] and at most 6 steps per test.
    - Retries once if validation fails.
    """
    # Ensure source has line numbers
    numbered_source = (
        source_code
        if source_code.lstrip().startswith("1:")
        else add_line_numbers(source_code)
    )

    analysis_json = analysis.model_dump_json(indent=2)
    prompt = make_generator_prompt(analysis_json, numbered_source)

    test_list: TestList = generate_json(
        prompt=prompt,
        schema_model=TestList,
        client=client,
        model=model,
        use_cache=use_cache,
        cache_dir=cache_dir,
    )

    errors = validate_test_cases(test_list.tests)
    if errors:
        # Retry once with validation feedback
        repair_prompt = make_generator_repair_prompt(
            previous_json=test_list.model_dump_json(indent=2),
            validation_errors=errors,
        )
        test_list = generate_json(
            prompt=repair_prompt,
            schema_model=TestList,
            client=client,
            model=model,
            use_cache=False,  # Bypass cache on retry
            cache_dir=cache_dir,
        )
        post_repair_errors = validate_test_cases(test_list.tests)
        if post_repair_errors:
            raise ValueError(
                f"Generated test suite failed validation after retry: {'; '.join(post_repair_errors)}"
            )

    tests = list(test_list.tests)

    # Coverage verification & targeted single top-up
    cat_counts = Counter(t.category for t in tests)
    missing_categories = [c for c in REQUIRED_CATEGORIES if cat_counts[c] < 1]
    boundary_needed = max(0, 4 - cat_counts["boundary"])

    if missing_categories or boundary_needed > 0:
        topup_prompt = make_generator_topup_prompt(
            analysis_json=analysis_json,
            numbered_source=numbered_source,
            missing_categories=missing_categories,
            boundary_needed=boundary_needed,
            existing_count=len(tests),
        )
        topup_list: TestList = generate_json(
            prompt=topup_prompt,
            schema_model=TestList,
            client=client,
            model=model,
            use_cache=use_cache,
            cache_dir=cache_dir,
        )

        # Merge with unique IDs
        existing_ids = {t.id for t in tests}
        next_num = len(tests) + 1
        for t in topup_list.tests:
            if t.id in existing_ids or not t.id.startswith("T"):
                while f"T{next_num:02d}" in existing_ids:
                    next_num += 1
                t.id = f"T{next_num:02d}"
            existing_ids.add(t.id)
            tests.append(t)

        post_topup_errors = validate_test_cases(tests, max_tests=25)
        if post_topup_errors:
            raise ValueError(
                f"Generated test suite failed validation after top-up: {'; '.join(post_topup_errors)}"
            )

    return tests
