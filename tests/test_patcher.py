"""Unit tests for agent/patcher.py."""

from pathlib import Path
import pytest

from agent.models import Finding, PatchHunk, PatchProposal
from agent.patcher import (
    apply_hunks_to_source,
    apply_patch_to_copy,
    apply_to_original,
    get_protected_ranges,
    render_diff,
    render_diff_rows,
    revert_original,
    validate_patch,
)

SAMPLE_SOURCE = """/*
 * Fan Controller Firmware
 * Specification comment block
 */
#include <Arduino.h>
#define DHTPIN 2

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


def _sample_finding(suspect_lines: list[int] = [14]) -> Finding:
    return Finding(
        id="F01",
        title="Off-by-one boundary comparison",
        failed_tests=["T01"],
        expected="Fan ON when temp >= 30.0",
        observed="Fan OFF when temp == 30.0",
        likely_cause="Strict greater-than instead of greater-or-equal",
        suspect_lines=suspect_lines,
        suggested_fix="Change > 30.0 to >= 30.0",
        severity="high",
    )


def test_get_protected_ranges():
    """get_protected_ranges detects spec block and preprocessor directives."""
    ranges = get_protected_ranges(SAMPLE_SOURCE)
    # Lines 1-4 is spec block
    assert (1, 4, "spec_comment_block") in ranges
    # Lines 5, 6 are preprocessor directives
    assert (5, 5, "preprocessor_directive") in ranges
    assert (6, 6, "preprocessor_directive") in ranges


def test_exact_match_hunk_application_succeeds():
    """Exact match hunk applies cleanly and validation check passes."""
    hunk = PatchHunk(
        id="h1",
        start_line=14,
        end_line=14,
        original_code="    if (temp > 30.0) {",
        new_code="    if (temp >= 30.0) {",
        explanation="Fix boundary comparison",
        confidence=0.95,
        fixes_tests=["T01"],
    )
    proposal = PatchProposal(hunks=[hunk], summary="Fix R1 threshold")
    findings = [_sample_finding([14])]

    validation = validate_patch(
        source=SAMPLE_SOURCE,
        proposal=proposal,
        findings=findings,
    )

    assert validation.ok is True
    check_map = {c.name: c.ok for c in validation.checks}
    assert check_map["exact_match"] is True
    assert check_map["non_overlapping"] is True
    assert check_map["protected_ranges"] is True
    assert check_map["scope_adherence"] is True
    assert check_map["hunk_limit"] is True
    assert check_map["line_limit"] is True
    assert check_map["spec_block_integrity"] is True

    patched = apply_hunks_to_source(SAMPLE_SOURCE, [hunk])
    assert "if (temp >= 30.0) {" in patched
    assert "if (temp > 30.0) {" not in patched


def test_mismatched_hunk_rejected():
    """Hunk with mismatched original_code is rejected."""
    hunk = PatchHunk(
        id="h1",
        start_line=14,
        end_line=14,
        original_code="    if (wrong_condition) {",
        new_code="    if (temp >= 30.0) {",
        explanation="Fix boundary comparison",
        confidence=0.9,
        fixes_tests=["T01"],
    )
    proposal = PatchProposal(hunks=[hunk], summary="Fix R1 threshold")
    validation = validate_patch(
        source=SAMPLE_SOURCE,
        proposal=proposal,
        findings=[_sample_finding([14])],
    )

    assert validation.ok is False
    check = next(c for c in validation.checks if c.name == "exact_match")
    assert check.ok is False


def test_overlapping_hunks_rejected():
    """Multiple hunks with overlapping line ranges are rejected."""
    hunk1 = PatchHunk(
        id="h1",
        start_line=13,
        end_line=14,
        original_code="    float temp = 25.0;\n    if (temp > 30.0) {",
        new_code="    float temp = 25.0;\n    if (temp >= 30.0) {",
        explanation="First hunk",
        confidence=0.9,
        fixes_tests=["T01"],
    )
    hunk2 = PatchHunk(
        id="h2",
        start_line=14,
        end_line=15,
        original_code="    if (temp > 30.0) {\n        digitalWrite(13, HIGH);",
        new_code="    if (temp >= 30.0) {\n        digitalWrite(13, HIGH);",
        explanation="Second overlapping hunk",
        confidence=0.8,
        fixes_tests=["T01"],
    )
    proposal = PatchProposal(hunks=[hunk1, hunk2], summary="Overlapping hunks")
    validation = validate_patch(
        source=SAMPLE_SOURCE,
        proposal=proposal,
        findings=[_sample_finding([14])],
    )

    assert validation.ok is False
    check = next(c for c in validation.checks if c.name == "non_overlapping")
    assert check.ok is False


def test_protected_ranges_rejected():
    """Hunk attempting to modify spec block or #include is rejected."""
    hunk_spec = PatchHunk(
        id="h_spec",
        start_line=2,
        end_line=3,
        original_code=" * Fan Controller Firmware\n * Specification comment block",
        new_code=" * Modified spec",
        explanation="Modifying spec block",
        confidence=0.9,
        fixes_tests=[],
    )
    proposal = PatchProposal(hunks=[hunk_spec], summary="Modify spec")
    validation = validate_patch(
        source=SAMPLE_SOURCE,
        proposal=proposal,
        findings=[_sample_finding([2])],
    )

    assert validation.ok is False
    check = next(c for c in validation.checks if c.name == "protected_ranges")
    assert check.ok is False

    hunk_include = PatchHunk(
        id="h_inc",
        start_line=5,
        end_line=5,
        original_code="#include <Arduino.h>",
        new_code="#include <Arduino.h>\n#include <Extra.h>",
        explanation="Add include",
        confidence=0.9,
        fixes_tests=[],
    )
    proposal2 = PatchProposal(hunks=[hunk_include], summary="Modify include")
    validation2 = validate_patch(
        source=SAMPLE_SOURCE,
        proposal=proposal2,
        findings=[_sample_finding([5])],
    )
    assert validation2.ok is False
    check2 = next(c for c in validation2.checks if c.name == "protected_ranges")
    assert check2.ok is False


def test_scope_adherence_rejected():
    """Hunk outside +-5 lines of finding suspect_lines is rejected."""
    # Finding suspect_lines is [14]. Line 8 is > 5 lines away (distance 6).
    hunk = PatchHunk(
        id="h_out",
        start_line=8,
        end_line=8,
        original_code="void setup() {",
        new_code="void setup_custom() {",
        explanation="Out of scope edit",
        confidence=0.5,
        fixes_tests=[],
    )
    proposal = PatchProposal(hunks=[hunk], summary="Out of scope change")
    validation = validate_patch(
        source=SAMPLE_SOURCE,
        proposal=proposal,
        findings=[_sample_finding([14])],
    )

    assert validation.ok is False
    check = next(c for c in validation.checks if c.name == "scope_adherence")
    assert check.ok is False


def test_line_and_hunk_limit_enforcement():
    """More than 3 hunks or more than 25 changed lines are rejected."""
    # 4 hunks
    hunks_4 = [
        PatchHunk(
            id=f"h{i}",
            start_line=13,
            end_line=13,
            original_code="    float temp = 25.0;",
            new_code="    float temp = 25.0;",
            explanation="Dummy",
            confidence=0.9,
            fixes_tests=[],
        )
        for i in range(4)
    ]
    prop_too_many_hunks = PatchProposal(hunks=hunks_4, summary="Too many hunks")
    val1 = validate_patch(SAMPLE_SOURCE, prop_too_many_hunks, [_sample_finding([13])])
    assert val1.ok is False
    check1 = next(c for c in val1.checks if c.name == "hunk_limit")
    assert check1.ok is False

    # More than 25 lines changed
    big_new_code = "\n".join([f"    int x{i} = {i};" for i in range(30)])
    hunk_big = PatchHunk(
        id="h_big",
        start_line=13,
        end_line=13,
        original_code="    float temp = 25.0;",
        new_code=big_new_code,
        explanation="Too many lines",
        confidence=0.9,
        fixes_tests=[],
    )
    prop_too_many_lines = PatchProposal(hunks=[hunk_big], summary="Too many lines")
    val2 = validate_patch(SAMPLE_SOURCE, prop_too_many_lines, [_sample_finding([13])])
    assert val2.ok is False
    check2 = next(c for c in val2.checks if c.name == "line_limit")
    assert check2.ok is False


def test_diff_rendering():
    """render_diff and render_diff_rows produce unified diff format."""
    hunk = PatchHunk(
        id="h1",
        start_line=14,
        end_line=14,
        original_code="    if (temp > 30.0) {",
        new_code="    if (temp >= 30.0) {",
        explanation="Fix threshold",
        confidence=0.9,
        fixes_tests=["T01"],
    )
    proposal = PatchProposal(hunks=[hunk], summary="Threshold fix")
    diff = render_diff(SAMPLE_SOURCE, proposal)

    assert "--- a/src/main.cpp" in diff
    assert "+++ b/src/main.cpp" in diff
    assert "-    if (temp > 30.0) {" in diff
    assert "+    if (temp >= 30.0) {" in diff

    rows = render_diff_rows(SAMPLE_SOURCE, proposal)
    assert any(r["type"] == "del" and "if (temp > 30.0) {" in r["content"] for r in rows)
    assert any(r["type"] == "add" and "if (temp >= 30.0) {" in r["content"] for r in rows)


def test_atomic_apply_to_copy_leaves_main_cpp_orig(tmp_path):
    """apply_patch_to_copy applies patch and creates main.cpp.orig."""
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)
    main_file = src_dir / "main.cpp"
    main_file.write_text(SAMPLE_SOURCE, encoding="utf-8")

    hunk = PatchHunk(
        id="h1",
        start_line=14,
        end_line=14,
        original_code="    if (temp > 30.0) {",
        new_code="    if (temp >= 30.0) {",
        explanation="Fix threshold",
        confidence=0.9,
        fixes_tests=["T01"],
    )
    proposal = PatchProposal(hunks=[hunk], summary="Fix threshold")

    apply_patch_to_copy(tmp_path, proposal)

    orig_backup = src_dir / "main.cpp.orig"
    assert orig_backup.is_file()
    assert orig_backup.read_text(encoding="utf-8") == SAMPLE_SOURCE

    updated_source = main_file.read_text(encoding="utf-8")
    assert "if (temp >= 30.0) {" in updated_source


def test_atomic_apply_to_original_and_revert(tmp_path):
    """apply_to_original leaves main.cpp.bak and revert_original restores byte-for-byte."""
    fw_dir = tmp_path / "firmware"
    src_dir = fw_dir / "src"
    src_dir.mkdir(parents=True)
    orig_file = src_dir / "main.cpp"
    orig_file.write_text(SAMPLE_SOURCE, encoding="utf-8")

    runs_dir = tmp_path / "runs"
    run_id = "test_run"

    hunk = PatchHunk(
        id="h1",
        start_line=14,
        end_line=14,
        original_code="    if (temp > 30.0) {",
        new_code="    if (temp >= 30.0) {",
        explanation="Fix threshold",
        confidence=0.9,
        fixes_tests=["T01"],
    )
    proposal = PatchProposal(hunks=[hunk], summary="Fix threshold")

    from agent.models import FixAttempt, PatchValidation
    attempt = FixAttempt(
        attempt_id="att-01",
        status="validated",
        proposal=proposal,
        validation=PatchValidation(ok=True, checks=[]),
        before_counts={},
    )

    # 1. Apply to original
    applied_file = apply_to_original(
        attempt=attempt,
        run_id=run_id,
        firmware_dir=fw_dir,
        runs_base_dir=runs_dir,
    )
    assert applied_file == orig_file
    assert attempt.status == "applied"
    assert "if (temp >= 30.0) {" in orig_file.read_text(encoding="utf-8")

    # Check that main.cpp.bak exists
    bak_in_fix = runs_dir / run_id / "fix" / "att-01" / "main.cpp.bak"
    bak_local = src_dir / "main.cpp.bak"
    assert bak_in_fix.is_file() or bak_local.is_file()

    # 2. Revert original
    reverted = revert_original(
        attempt=attempt,
        run_id=run_id,
        firmware_dir=fw_dir,
        runs_base_dir=runs_dir,
    )
    assert reverted is True
    assert attempt.status == "reverted"

    # Verify byte-for-byte restoration
    assert orig_file.read_text(encoding="utf-8") == SAMPLE_SOURCE
    # Check that backup file was NOT deleted
    if bak_in_fix.is_file():
        assert bak_in_fix.read_text(encoding="utf-8") == SAMPLE_SOURCE
    if bak_local.is_file():
        assert bak_local.read_text(encoding="utf-8") == SAMPLE_SOURCE


def test_reconcile_hunks_fixes_llm_end_line_off_by_one():
    """When LLM provides end_line off-by-one or omitting blank lines, reconcile_hunks aligns bounds."""
    # Line 12 is 'void loop() {'
    # Line 13 is '    float temp = 25.0;'
    # LLM says start_line: 12, end_line: 12 (1 line claimed), but original_code has 2 lines:
    hunk = PatchHunk(
        id="h_off",
        start_line=12,
        end_line=12,
        original_code="void loop() {\n    float temp = 25.0;",
        new_code="void loop() {\n    float temp = 26.0;",
        explanation="Test line bound reconciliation",
        confidence=0.9,
        fixes_tests=[],
    )
    proposal = PatchProposal(hunks=[hunk], summary="Test reconciliation")
    validation = validate_patch(
        source=SAMPLE_SOURCE,
        proposal=proposal,
        findings=[_sample_finding([12])],
    )

    assert validation.ok is True
    # Hunk should have been aligned to end_line: 13
    assert hunk.end_line == 13
    exact_check = next(c for c in validation.checks if c.name == "exact_match")
    assert exact_check.ok is True
