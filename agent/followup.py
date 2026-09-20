"""Autonomous follow-up loop: generates targeted probing tests around detected failures."""

from typing import Any, Optional

from agent.llm import generate_json
from agent.models import (
    Expectation,
    FirmwareAnalysis,
    TestCase,
    TestList,
    TestResult,
    TestStep,
)
from agent.prompts import make_followup_prompt
from agent.rootcause import summarize_failed_tests


def _fallback_followup_tests(
    failed_results: list[TestResult],
    test_cases: list[TestCase],
    round_num: int = 1,
) -> list[TestCase]:
    """Deterministic fallback to generate focused probing tests around failures."""
    test_map = {t.id: t for t in test_cases}
    probes: list[TestCase] = []
    idx = 1

    for r in failed_results:
        t = test_map.get(r.test_id)
        if not t:
            continue

        # 1. Probe around boundary failures (e.g. 30.0 C)
        if (
            t.category == "boundary"
            or any(s.set_temp == 30.0 for s in t.steps)
        ):
            probes.append(
                TestCase(
                    id=f"F{idx:02d}",
                    name="Probing Boundary Below Threshold (29.9 C)",
                    category="followup",
                    steps=[TestStep(set_temp=29.9, wait_ms=2500)],
                    expect=[
                        Expectation(
                            serial_contains="temp=29.9 fan=OFF", spec_ref="R3"
                        )
                    ],
                    must_not=[],
                    rationale="Probe behavior immediately below 30.0 C threshold.",
                    round=round_num,
                )
            )
            idx += 1

            probes.append(
                TestCase(
                    id=f"F{idx:02d}",
                    name="Probing Boundary Above Threshold (30.1 C)",
                    category="followup",
                    steps=[TestStep(set_temp=30.1, wait_ms=2500)],
                    expect=[
                        Expectation(
                            serial_contains="temp=30.1 fan=ON", spec_ref="R1"
                        )
                    ],
                    must_not=[],
                    rationale="Probe behavior immediately above 30.0 C threshold.",
                    round=round_num,
                )
            )
            idx += 1

        # 2. Probe around hysteresis failures (e.g. 31 -> 29)
        elif t.category in ("sequence", "recovery") or any(
            "hysteresis" in (t.name or "").lower() for _ in [0]
        ):
            probes.append(
                TestCase(
                    id=f"F{idx:02d}",
                    name="Probing Hysteresis Lower Bound (31.0 -> 28.0 C)",
                    category="followup",
                    steps=[
                        TestStep(set_temp=31.0, wait_ms=2500),
                        TestStep(set_temp=28.0, wait_ms=2500),
                    ],
                    expect=[
                        Expectation(
                            serial_contains="temp=28.0 fan=ON", spec_ref="R2"
                        )
                    ],
                    must_not=[],
                    rationale="Probe fan state retention at lower hysteresis limit (28.0 C).",
                    round=round_num,
                )
            )
            idx += 1

            probes.append(
                TestCase(
                    id=f"F{idx:02d}",
                    name="Probing Hysteresis Turn-Off Transition (31.0 -> 27.9 C)",
                    category="followup",
                    steps=[
                        TestStep(set_temp=31.0, wait_ms=2500),
                        TestStep(set_temp=27.9, wait_ms=2500),
                    ],
                    expect=[
                        Expectation(
                            serial_contains="temp=27.9 fan=OFF", spec_ref="R2"
                        )
                    ],
                    must_not=[],
                    rationale="Verify fan turns OFF once temperature drops below 28.0 C.",
                    round=round_num,
                )
            )
            idx += 1

        # 3. Probe around sensor disconnection
        elif t.category == "sensor_failure" or t.sensor == "disconnected":
            probes.append(
                TestCase(
                    id=f"F{idx:02d}",
                    name="Probing Sensor Failure Fail-Safe",
                    category="followup",
                    sensor="disconnected",
                    steps=[TestStep(wait_ms=3000)],
                    expect=[
                        Expectation(
                            serial_contains="[ERROR] SENSOR_FAIL",
                            spec_ref="R5",
                        ),
                        Expectation(serial_contains="fan=ON", spec_ref="R5"),
                    ],
                    must_not=[],
                    rationale="Probe sensor fail-safe trigger under persistent disconnected circuit.",
                    round=round_num,
                )
            )
            idx += 1

        if len(probes) >= 6:
            break

    return probes[:6]


def generate_followup_tests(
    failed_results: list[TestResult],
    test_cases: list[TestCase],
    analysis: FirmwareAnalysis,
    numbered_source: str,
    round_num: int = 1,
    client: Any = None,
) -> list[TestCase]:
    """Generate focused probing tests investigating failures from previous round."""
    relevant_failures = [
        r for r in failed_results if r.status in ("FAIL", "ERROR")
    ]
    if not relevant_failures:
        return []

    failed_summary = summarize_failed_tests(relevant_failures, test_cases)
    prompt = make_followup_prompt(
        failed_tests_summary=failed_summary,
        analysis_json=analysis.model_dump_json(indent=2),
        numbered_source=numbered_source,
        round_num=round_num,
    )

    try:
        test_list = generate_json(
            prompt=prompt,
            schema_model=TestList,
            client=client,
        )
        if test_list and test_list.tests:
            sanitized: list[TestCase] = []
            for i, t in enumerate(test_list.tests[:6], start=1):
                t_id = t.id if t.id.startswith("F") else f"F{i:02d}"
                sanitized.append(
                    TestCase(
                        id=t_id,
                        name=t.name,
                        category="followup",
                        sensor=t.sensor,
                        steps=t.steps,
                        expect=t.expect,
                        must_not=t.must_not,
                        rationale=t.rationale,
                        round=round_num,
                    )
                )
            if sanitized:
                return sanitized
    except Exception:
        pass

    # Deterministic fallback when LLM is unavailable
    return _fallback_followup_tests(
        failed_results=relevant_failures,
        test_cases=test_cases,
        round_num=round_num,
    )
