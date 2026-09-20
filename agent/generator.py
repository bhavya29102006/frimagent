"""Test generator module: analysis + source -> TestCase list."""

from pathlib import Path
from google import genai
from agent.analyzer import add_line_numbers
from agent.llm import generate_json
from agent.models import FirmwareAnalysis, TestCase, TestList
from agent.prompts import make_generator_prompt, make_generator_repair_prompt


def validate_test_cases(tests: list[TestCase]) -> list[str]:
    """Validate a list of TestCase objects against requirements.

    Returns:
        list[str]: List of validation error messages, empty if valid.
    """
    errors: list[str] = []

    # 1. Count: 12 to 20 tests
    if len(tests) < 12:
        errors.append(f"Expected at least 12 tests, got {len(tests)}")
    elif len(tests) > 20:
        errors.append(f"Expected at most 20 tests, got {len(tests)}")

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
    - 12 to 20 tests covering at least 6 categories.
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

    return test_list.tests
