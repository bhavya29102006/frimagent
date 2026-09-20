"""Root-cause analyzer: failed results + numbered source -> Finding objects."""

import json
from pathlib import Path
from typing import Any, Optional

from agent.llm import generate_json
from agent.models import (
    Finding,
    FindingList,
    FirmwareAnalysis,
    SpecRule,
    TestCase,
    TestResult,
)
from agent.prompts import make_rootcause_prompt


def number_source_code(source_code: str) -> str:
    """Prefix each line of source code with its 1-indexed line number."""
    lines = source_code.splitlines()
    return "\n".join(f"{i + 1:3d} | {line}" for i, line in enumerate(lines))


def summarize_spec_rules(spec_rules: list[SpecRule]) -> str:
    """Format spec rules for LLM prompt."""
    if not spec_rules:
        return "No explicit specification rules provided."
    lines = []
    for r in spec_rules:
        lines_ref = (
            f" (source lines: {r.source_lines})" if r.source_lines else ""
        )
        lines.append(f"- {r.id}: {r.text}{lines_ref}")
    return "\n".join(lines)


def summarize_failed_tests(
    failed_results: list[TestResult],
    test_cases: list[TestCase],
) -> str:
    """Format failed test outcomes for LLM root cause analysis."""
    test_map = {t.id: t for t in test_cases}
    summary_blocks = []

    for r in failed_results:
        t = test_map.get(r.test_id)
        name = t.name if t else r.test_id
        category = t.category if t else "unknown"
        steps_desc = (
            ", ".join(
                f"set_temp={s.set_temp} (wait {s.wait_ms}ms)" for s in t.steps
            )
            if t
            else "unknown"
        )
        spec_refs = (
            list(set(e.spec_ref for e in t.expect if e.spec_ref)) if t else []
        )

        block = [
            f"- Test ID: {r.test_id} ({name})",
            f"  Category: {category}",
            f"  Steps: {steps_desc}",
            f"  Associated Spec: {', '.join(spec_refs) if spec_refs else 'None'}",
            f"  Expected serial contains: {r.expected}",
            f"  Missing expected: {r.missing_expected}",
            f"  Observed lines: {r.observed_lines}",
            f"  Violated must_not: {r.violated_must_not}",
            f"  Exit code: {r.exit_code}",
            f"  Error detail: {r.error_message}",
        ]
        summary_blocks.append("\n".join(block))

    return "\n\n".join(summary_blocks)


def _fallback_root_cause(
    failed_results: list[TestResult],
    test_cases: list[TestCase],
    analysis: FirmwareAnalysis,
) -> list[Finding]:
    """Rule-based fallback when LLM is offline or fails."""
    test_map = {t.id: t for t in test_cases}
    rule_map = {r.id: r for r in analysis.spec_rules}

    # Group by first spec_ref if present, else by test_id
    grouped: dict[str, list[TestResult]] = {}
    for r in failed_results:
        t = test_map.get(r.test_id)
        spec_ref = "UNKNOWN"
        if t and t.expect and t.expect[0].spec_ref:
            spec_ref = t.expect[0].spec_ref
        grouped.setdefault(spec_ref, []).append(r)

    findings: list[Finding] = []
    idx = 1
    for spec_ref, group in grouped.items():
        rule = rule_map.get(spec_ref)
        failed_ids = [r.test_id for r in group]
        first_res = group[0]
        t = test_map.get(first_res.test_id)

        title = f"Defect in {rule.text if rule else f'test cases {failed_ids}'}"
        expected_str = ", ".join(first_res.expected)
        observed_str = (
            ", ".join(first_res.observed_lines)
            if first_res.observed_lines
            else (first_res.error_message or "No output")
        )

        suspect_lines = rule.source_lines if rule else []
        severity = "medium"
        if (
            t
            and t.category == "sensor_failure"
            or "SENSOR" in "".join(first_res.expected)
        ):
            severity = "high"

        findings.append(
            Finding(
                id=f"FIND-{idx}",
                title=title[:80],
                failed_tests=failed_ids,
                spec_ref=spec_ref if spec_ref != "UNKNOWN" else None,
                expected=f"Expected: {expected_str}",
                observed=f"Observed: {observed_str}",
                likely_cause="Firmware serial output did not match expected specification conditions.",
                suspect_lines=suspect_lines,
                suggested_fix="Verify comparison operators, error handling, and state hysteresis in the control loop.",
                severity=severity,  # type: ignore
            )
        )
        idx += 1

    return findings


def analyze_root_causes(
    failed_results: list[TestResult],
    test_cases: list[TestCase],
    analysis: FirmwareAnalysis,
    numbered_source: str,
    client: Any = None,
) -> list[Finding]:
    """Diagnose root cause defects for failed tests using Gemini with fallback."""
    # Only analyze failed or errored tests
    relevant_failures = [
        r for r in failed_results if r.status in ("FAIL", "ERROR")
    ]
    if not relevant_failures:
        return []

    spec_rules_summary = summarize_spec_rules(analysis.spec_rules)
    failed_tests_summary = summarize_failed_tests(
        relevant_failures, test_cases
    )

    prompt = make_rootcause_prompt(
        numbered_source=numbered_source,
        spec_rules_summary=spec_rules_summary,
        failed_tests_summary=failed_tests_summary,
    )

    try:
        finding_list = generate_json(
            prompt=prompt,
            schema_model=FindingList,
            client=client,
        )
        if finding_list and finding_list.findings:
            return finding_list.findings
    except Exception:
        pass

    # Use deterministic fallback if LLM call fails
    return _fallback_root_cause(relevant_failures, test_cases, analysis)


def run_root_cause(
    run_dir: Path | str,
    firmware_source_path: Path | str | None = None,
    client: Any = None,
) -> list[Finding]:
    """Load run artifacts from run_dir, execute root cause analysis, and save findings.json."""
    dir_path = Path(run_dir)
    results_file = dir_path / "results.json"
    tests_file = dir_path / "tests.json"
    analysis_file = dir_path / "analysis.json"

    if not results_file.is_file():
        raise FileNotFoundError(f"results.json not found in {run_dir}")
    if not tests_file.is_file():
        raise FileNotFoundError(f"tests.json not found in {run_dir}")
    if not analysis_file.is_file():
        raise FileNotFoundError(f"analysis.json not found in {run_dir}")

    # Load results
    results_raw = json.loads(results_file.read_text(encoding="utf-8"))
    results = [TestResult.model_validate(r) for r in results_raw]

    # Load tests
    tests_raw = json.loads(tests_file.read_text(encoding="utf-8"))
    test_list = (
        tests_raw.get("tests", [])
        if isinstance(tests_raw, dict)
        else tests_raw
    )
    tests = [TestCase.model_validate(t) for t in test_list]

    # Load analysis
    analysis_raw = json.loads(analysis_file.read_text(encoding="utf-8"))
    analysis = FirmwareAnalysis.model_validate(analysis_raw)

    # Load source code
    source_candidates = [
        firmware_source_path,
        dir_path / "firmware_source.txt",
        Path("firmware/fan_controller/src/main.cpp"),
    ]
    source_code = ""
    for cand in source_candidates:
        if cand and Path(cand).is_file():
            source_code = Path(cand).read_text(encoding="utf-8")
            break

    numbered_source = (
        number_source_code(source_code)
        if source_code
        else "No source code available."
    )

    findings = analyze_root_causes(
        failed_results=results,
        test_cases=tests,
        analysis=analysis,
        numbered_source=numbered_source,
        client=client,
    )

    # Save findings.json
    findings_data = [f.model_dump() for f in findings]
    (dir_path / "findings.json").write_text(
        json.dumps(findings_data, indent=2), encoding="utf-8"
    )

    return findings
