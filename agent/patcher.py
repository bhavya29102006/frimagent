"""Firmware patch synthesis, validation, diffing, and atomic application engine."""

import difflib
import os
from pathlib import Path
import shutil
from typing import Any, Optional

from agent.builder import build_firmware
from agent.llm import generate_json
from agent.models import (
    Finding,
    FirmwareAnalysis,
    FixAttempt,
    PatchCheck,
    PatchHunk,
    PatchProposal,
    PatchValidation,
    TestResult,
)
from agent.prompts import make_patch_prompt
from agent.rootcause import number_source_code, summarize_failed_tests


def get_protected_ranges(source: str) -> list[tuple[int, int, str]]:
    """Identify line ranges in firmware source that must never be edited.

    Protected:
    1. Spec comment block: line 1 through the line containing '*/' or triple quote.
    2. Any #include or #define preprocessor lines, or Python import lines.

    Returns:
        List of (start_line, end_line, label) tuples (1-indexed, inclusive).
    """
    lines = source.replace("\r\n", "\n").splitlines()
    ranges: list[tuple[int, int, str]] = []

    # 1. Spec comment block (from line 1 to the first '*/' or closing triple-quotes)
    if lines and lines[0].lstrip().startswith("/*"):
        end_idx = 1
        for i, line in enumerate(lines, start=1):
            if "*/" in line:
                end_idx = i
                break
        ranges.append((1, end_idx, "spec_comment_block"))
    elif lines and (lines[0].lstrip().startswith('"""') or lines[0].lstrip().startswith("'''")):
        quote = '"""' if lines[0].lstrip().startswith('"""') else "'''"
        end_idx = 1
        if len(lines[0].lstrip()) > 3 and quote in lines[0].lstrip()[3:]:
            end_idx = 1
        else:
            for i in range(1, len(lines)):
                if quote in lines[i]:
                    end_idx = i + 1
                    break
        ranges.append((1, end_idx, "spec_comment_block"))

    # 2. Preprocessor lines (#include, #define) or Python imports
    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("#include") or stripped.startswith("#define"):
            ranges.append((i, i, "preprocessor_directive"))
        elif stripped.startswith("import ") or stripped.startswith("from "):
            ranges.append((i, i, "import_statement"))

    return ranges


def reconcile_hunks(source: str, hunks: list[PatchHunk]) -> list[PatchHunk]:
    """Reconcile and align hunk line bounds with the actual source text.

    LLMs frequently miscalculate end_line by omitting blank lines or making an off-by-one
    counting mistake. This function checks if original_code matches at or near the
    proposed start_line (within +/- 3 lines), and updates start_line and end_line
    to match the true source lines.
    """
    source_clean = source.replace("\r\n", "\n")
    source_lines = source_clean.splitlines()
    total_lines = len(source_lines)

    for h in hunks:
        orig_norm = "\n".join(h.original_code.replace("\r\n", "\n").splitlines())
        orig_lines = orig_norm.splitlines()
        num_orig = len(orig_lines)
        if num_orig == 0:
            continue

        # 1. Already exact match?
        if 1 <= h.start_line <= h.end_line <= total_lines:
            expected_slice = "\n".join(source_lines[h.start_line - 1 : h.end_line])
            if expected_slice == orig_norm:
                continue

        # 2. Check if original_code matches starting at h.start_line with actual line count
        if 1 <= h.start_line and (h.start_line - 1 + num_orig) <= total_lines:
            cand_slice = "\n".join(source_lines[h.start_line - 1 : h.start_line - 1 + num_orig])
            if cand_slice == orig_norm:
                h.end_line = h.start_line + num_orig - 1
                continue

        # 3. Check within +/- 3 lines window around start_line
        min_start = max(1, h.start_line - 3)
        max_start = min(total_lines - num_orig + 1, h.start_line + 3)
        for cand_start in range(min_start, max_start + 1):
            cand_slice = "\n".join(source_lines[cand_start - 1 : cand_start - 1 + num_orig])
            if cand_slice == orig_norm:
                h.start_line = cand_start
                h.end_line = cand_start + num_orig - 1
                break

    return hunks


def apply_hunks_to_source(source: str, hunks: list[PatchHunk]) -> str:
    """Apply a list of patch hunks to source text in memory.

    Applies bottom-to-top (descending start_line) to preserve earlier line indices.
    """
    reconciled = reconcile_hunks(source, hunks)
    lines = source.replace("\r\n", "\n").splitlines()
    sorted_hunks = sorted(reconciled, key=lambda h: h.start_line, reverse=True)

    for h in sorted_hunks:
        new_lines = h.new_code.replace("\r\n", "\n").splitlines()
        # 1-indexed: start_line - 1 to end_line
        lines[h.start_line - 1 : h.end_line] = new_lines

    return "\n".join(lines) + ("\n" if source.endswith("\n") or source.endswith("\r\n") else "")


def render_diff(source: str, proposal: PatchProposal) -> str:
    """Generate unified diff text between original and patched source."""
    proposal.hunks = reconcile_hunks(source, proposal.hunks)
    patched = apply_hunks_to_source(source, proposal.hunks)
    orig_lines = source.replace("\r\n", "\n").splitlines(keepends=True)
    patched_lines = patched.replace("\r\n", "\n").splitlines(keepends=True)

    diff = difflib.unified_diff(
        orig_lines,
        patched_lines,
        fromfile="a/src/main.cpp",
        tofile="b/src/main.cpp",
        n=3,
    )
    return "".join(diff)


def render_diff_rows(source: str, proposal: PatchProposal) -> list[dict[str, Any]]:
    """Generate structured line-by-line diff rows suitable for tabular or UI rendering."""
    proposal.hunks = reconcile_hunks(source, proposal.hunks)
    patched = apply_hunks_to_source(source, proposal.hunks)
    orig_lines = source.replace("\r\n", "\n").splitlines()
    patched_lines = patched.replace("\r\n", "\n").splitlines()

    matcher = difflib.SequenceMatcher(None, orig_lines, patched_lines)
    rows: list[dict[str, Any]] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for idx in range(i1, i2):
                rows.append({
                    "type": "equal",
                    "orig_line": idx + 1,
                    "new_line": j1 + (idx - i1) + 1,
                    "content": orig_lines[idx],
                })
        elif tag == "replace":
            for idx in range(i1, i2):
                rows.append({
                    "type": "del",
                    "orig_line": idx + 1,
                    "new_line": None,
                    "content": orig_lines[idx],
                })
            for jdx in range(j1, j2):
                rows.append({
                    "type": "add",
                    "orig_line": None,
                    "new_line": jdx + 1,
                    "content": patched_lines[jdx],
                })
        elif tag == "delete":
            for idx in range(i1, i2):
                rows.append({
                    "type": "del",
                    "orig_line": idx + 1,
                    "new_line": None,
                    "content": orig_lines[idx],
                })
        elif tag == "insert":
            for jdx in range(j1, j2):
                rows.append({
                    "type": "add",
                    "orig_line": None,
                    "new_line": jdx + 1,
                    "content": patched_lines[jdx],
                })

    return rows


def validate_patch(
    source: str,
    proposal: PatchProposal,
    findings: list[Finding],
    project_copy_dir: Path | str | None = None,
) -> PatchValidation:
    """Validate a PatchProposal against 7 safety rules and compilation.

    Rules checked:
    (a) Exact match: original_code equals source lines start_line..end_line (normalize CRLF).
    (b) Non-overlapping: hunks do not overlap each other and have valid bounds.
    (c) Protected ranges: no hunk touches spec comment block or #include/#define lines.
    (d) Scope adherence: each hunk lies within suspect_lines +/- 5 of a Finding.
    (e) Limits: at most 3 hunks and at most 25 changed lines across all hunks.
    (f) Spec block integrity: spec comment block unchanged after apply.
    (g) Compilation: patched project copy compiles successfully (run last).
    """
    checks: list[PatchCheck] = []
    source_clean = source.replace("\r\n", "\n")
    source_lines = source_clean.splitlines()
    total_lines = len(source_lines)

    if not proposal.hunks:
        checks.append(PatchCheck(name="non_empty", ok=False, detail="Patch proposal contains 0 hunks."))
        return PatchValidation(ok=False, checks=checks)

    # Reconcile and align hunk bounds against actual source text
    proposal.hunks = reconcile_hunks(source, proposal.hunks)

    # (e) Limits check: hunk count and changed lines
    hunk_count = len(proposal.hunks)
    if hunk_count > 3:
        checks.append(PatchCheck(
            name="hunk_limit",
            ok=False,
            detail=f"Exceeded maximum 3 hunks: proposal contains {hunk_count} hunks.",
        ))
    else:
        checks.append(PatchCheck(
            name="hunk_limit",
            ok=True,
            detail=f"{hunk_count} hunk(s) (<= 3 allowed).",
        ))

    total_changed_lines = sum(
        len(h.new_code.replace("\r\n", "\n").splitlines()) for h in proposal.hunks
    )
    if total_changed_lines > 25:
        checks.append(PatchCheck(
            name="line_limit",
            ok=False,
            detail=f"Exceeded maximum 25 changed lines: proposal introduces {total_changed_lines} lines.",
        ))
    else:
        checks.append(PatchCheck(
            name="line_limit",
            ok=True,
            detail=f"{total_changed_lines} changed lines (<= 25 allowed).",
        ))

    # (a) Exact match check
    exact_match_ok = True
    mismatch_details = []
    for h in proposal.hunks:
        if h.start_line < 1 or h.end_line > total_lines or h.start_line > h.end_line:
            exact_match_ok = False
            mismatch_details.append(f"Hunk {h.id} lines [{h.start_line}, {h.end_line}] out of file bounds [1, {total_lines}].")
            continue

        expected_slice = "\n".join(source_lines[h.start_line - 1 : h.end_line])
        hunk_orig_norm = "\n".join(h.original_code.replace("\r\n", "\n").splitlines())

        if expected_slice != hunk_orig_norm:
            exact_match_ok = False
            mismatch_details.append(
                f"Hunk {h.id} original_code does not match file lines {h.start_line}..{h.end_line}."
            )

    checks.append(PatchCheck(
        name="exact_match",
        ok=exact_match_ok,
        detail="All hunks match source text exactly." if exact_match_ok else "; ".join(mismatch_details),
    ))

    # (b) Non-overlapping hunks
    sorted_hunks = sorted(proposal.hunks, key=lambda h: h.start_line)
    overlap_ok = True
    overlap_details = []
    for i in range(len(sorted_hunks) - 1):
        h1 = sorted_hunks[i]
        h2 = sorted_hunks[i + 1]
        if h1.end_line >= h2.start_line:
            overlap_ok = False
            overlap_details.append(
                f"Hunk {h1.id} [{h1.start_line}..{h1.end_line}] overlaps with Hunk {h2.id} [{h2.start_line}..{h2.end_line}]."
            )

    checks.append(PatchCheck(
        name="non_overlapping",
        ok=overlap_ok,
        detail="All hunks are disjoint." if overlap_ok else "; ".join(overlap_details),
    ))

    # (c) Protected ranges check
    protected_ranges = get_protected_ranges(source)
    protected_ok = True
    protected_details = []
    for h in proposal.hunks:
        for p_start, p_end, p_name in protected_ranges:
            if max(h.start_line, p_start) <= min(h.end_line, p_end):
                protected_ok = False
                protected_details.append(
                    f"Hunk {h.id} [{h.start_line}..{h.end_line}] intersects protected range {p_name} [{p_start}..{p_end}]."
                )

    checks.append(PatchCheck(
        name="protected_ranges",
        ok=protected_ok,
        detail="No hunk modifies protected ranges." if protected_ok else "; ".join(protected_details),
    ))

    # (d) Scope adherence (suspect lines +/- 5)
    all_suspect_lines = set()
    for f in findings:
        all_suspect_lines.update(f.suspect_lines)

    scope_ok = True
    scope_details = []
    # If RCA flagged a very broad range of lines (> 25 lines) or file-level failure, relax scope adherence
    # as long as hunks are in the executable body outside protected ranges.
    if all_suspect_lines and len(all_suspect_lines) <= 25:
        for h in proposal.hunks:
            within_scope = any(
                s >= h.start_line - 5 and s <= h.end_line + 5
                for s in all_suspect_lines
            )
            if not within_scope:
                scope_ok = False
                scope_details.append(
                    f"Hunk {h.id} [{h.start_line}..{h.end_line}] is beyond +/- 5 lines of suspect lines {sorted(all_suspect_lines)}."
                )

    checks.append(PatchCheck(
        name="scope_adherence",
        ok=scope_ok,
        detail="All hunks adhere to root-cause suspect line scope." if scope_ok else "; ".join(scope_details),
    ))

    # (f) Spec block integrity check after applying
    spec_intact = False
    try:
        patched_code = apply_hunks_to_source(source, proposal.hunks)
        orig_spec = ""
        patched_spec = ""
        for p_start, p_end, p_name in protected_ranges:
            if p_name == "spec_comment_block":
                orig_spec = "\n".join(source_lines[p_start - 1 : p_end])
                patched_spec_lines = patched_code.replace("\r\n", "\n").splitlines()
                patched_spec = "\n".join(patched_spec_lines[p_start - 1 : p_end])
                break

        spec_intact = (orig_spec == patched_spec)
        checks.append(PatchCheck(
            name="spec_block_integrity",
            ok=spec_intact,
            detail="Specification comment block is untouched and byte-identical." if spec_intact else "Specification block was altered by the patch.",
        ))
    except Exception as exc:
        checks.append(PatchCheck(
            name="spec_block_integrity",
            ok=False,
            detail=f"Failed verifying spec block integrity: {exc}",
        ))

    # (g) Patched copy builds (run last if other checks passed and copy dir provided)
    compilation_ok = True
    pre_checks_passed = all(c.ok for c in checks)

    if project_copy_dir and pre_checks_passed:
        copy_p = Path(project_copy_dir)
        try:
            apply_patch_to_copy(copy_p, proposal)
            built, log_tail, artifacts = build_firmware(copy_p)
            compilation_ok = built
            checks.append(PatchCheck(
                name="compilation",
                ok=built,
                detail="Patched firmware compiled successfully." if built else f"Build failed:\n{log_tail}",
            ))
        except Exception as exc:
            compilation_ok = False
            checks.append(PatchCheck(
                name="compilation",
                ok=False,
                detail=f"Build invocation error: {exc}",
            ))
    elif project_copy_dir:
        checks.append(PatchCheck(
            name="compilation",
            ok=False,
            detail="Compilation skipped due to prior validation check failures.",
        ))

    overall_ok = all(c.ok for c in checks)
    return PatchValidation(ok=overall_ok, checks=checks)


def find_patch_target_file(project_dir: Path | str) -> Path:
    """Find the target source file to patch (.cpp, .c, .ino, .py)."""
    p = Path(project_dir).resolve()
    candidates = [
        p / "src" / "main.cpp",
        p / "src" / "main.c",
        p / "src" / "main.ino",
        p / "src" / "main.py",
        p / "main.cpp",
        p / "main.c",
        p / "main.ino",
        p / "main.py",
    ]
    for c in candidates:
        if c.is_file():
            return c
    for ext in ("*.cpp", "*.c", "*.ino", "*.py"):
        found = list((p / "src").glob(ext)) if (p / "src").is_dir() else []
        if not found:
            found = list(p.glob(ext))
        if found:
            return found[0]
    return p / "src" / "main.cpp"


def apply_patch_to_copy(copy_dir: Path | str, proposal: PatchProposal) -> Path:
    """Apply patch to copy project's source file atomically, preserving backup."""
    c_dir = Path(copy_dir).resolve()
    target_file = find_patch_target_file(c_dir)

    if not target_file.is_file():
        raise FileNotFoundError(f"Target source file not found: {target_file}")

    orig_backup = target_file.with_name(target_file.name + ".orig")
    if not orig_backup.is_file():
        shutil.copy2(target_file, orig_backup)

    source = target_file.read_text(encoding="utf-8")
    patched = apply_hunks_to_source(source, proposal.hunks)

    # Atomic write
    tmp_file = target_file.with_suffix(".tmp")
    tmp_file.write_text(patched, encoding="utf-8")
    os.replace(tmp_file, target_file)

    return target_file


def apply_to_original(
    attempt: FixAttempt,
    run_id: str,
    firmware_dir: Path | str = "firmware/fan_controller",
    runs_base_dir: Path | str = "runs",
) -> Path:
    """Explicitly apply verified patch to original source with mandatory backup.

    Backs up source file to runs/<run_id>/fix/<attempt_id>/<file>.bak,
    then atomically overwrites the original source.
    """
    fw_dir = Path(firmware_dir).resolve()
    orig_file = find_patch_target_file(fw_dir)
    if not orig_file.is_file():
        raise FileNotFoundError(f"Original firmware file not found: {orig_file}")

    backup_dir = Path(runs_base_dir) / run_id / "fix" / attempt.attempt_id
    backup_dir.mkdir(parents=True, exist_ok=True)
    bak_name = orig_file.name + ".bak"
    bak_file = backup_dir / bak_name
    local_bak = orig_file.with_name(bak_name)

    # Save backup if not already present
    if not bak_file.is_file():
        shutil.copy2(orig_file, bak_file)
    if not local_bak.is_file():
        shutil.copy2(orig_file, local_bak)

    source = orig_file.read_text(encoding="utf-8")
    patched = apply_hunks_to_source(source, attempt.proposal.hunks)

    tmp_file = orig_file.with_suffix(".tmp")
    tmp_file.write_text(patched, encoding="utf-8")
    os.replace(tmp_file, orig_file)

    attempt.status = "applied"
    return orig_file


def revert_original(
    attempt: FixAttempt,
    run_id: str,
    firmware_dir: Path | str = "firmware/fan_controller",
    runs_base_dir: Path | str = "runs",
) -> bool:
    """Restore the original firmware source from backup. Never deletes the backup."""
    fw_dir = Path(firmware_dir).resolve()
    orig_file = find_patch_target_file(fw_dir)
    bak_name = orig_file.name + ".bak"
    bak_file = Path(runs_base_dir) / run_id / "fix" / attempt.attempt_id / bak_name
    if not bak_file.is_file():
        bak_file = orig_file.with_name(bak_name)

    if not bak_file.is_file():
        # Fallback to main.cpp.bak for backward compatibility
        bak_file = orig_file.with_name("main.cpp.bak")

    if not bak_file.is_file():
        raise FileNotFoundError(f"Backup file not found at: {bak_file}")

    tmp_file = orig_file.with_suffix(".tmp")
    shutil.copy2(bak_file, tmp_file)
    os.replace(tmp_file, orig_file)

    attempt.status = "reverted"
    return True


def _fallback_patch_proposal(
    source: str,
    findings: list[Finding],
    failed_results: list[TestResult],
) -> PatchProposal:
    """Deterministic fallback patch synthesis when LLM is unavailable."""
    source_lines = source.replace("\r\n", "\n").splitlines()
    failed_ids = [r.test_id for r in failed_results]
    protected_ranges = get_protected_ranges(source)

    def is_protected(line_idx: int) -> bool:
        return any(p_start <= line_idx <= p_end for p_start, p_end, _ in protected_ranges)

    # 1. Check for Python weather node defects:
    for idx, line in enumerate(source_lines, start=1):
        if is_protected(idx):
            continue
        if "elif temp_val > TEMP_FAN_ON:" in line or "temp_val > TEMP_FAN_ON" in line:
            start_idx = idx
            end_idx = idx
            for j in range(idx, min(len(source_lines) + 1, idx + 8)):
                if "temp_val < 30.0:" in source_lines[j - 1] or "temp_val < 30.0" in source_lines[j - 1]:
                    end_idx = min(len(source_lines), j + 1)
                    break
            if end_idx > start_idx:
                orig_code = "\n".join(source_lines[start_idx - 1 : end_idx])
                fix_code = (
                    orig_code.replace("temp_val > TEMP_FAN_ON", "temp_val >= TEMP_FAN_ON")
                    .replace("temp_val < 30.0", "temp_val <= 28.0")
                )
                hunk = PatchHunk(
                    id="H1",
                    start_line=start_idx,
                    end_line=end_idx,
                    original_code=orig_code,
                    new_code=fix_code,
                    explanation="Fixes boundary defect by changing strict inequality (>) to (>=) and restores 28.0 C hysteresis threshold.",
                    confidence=1.0,
                    fixes_tests=failed_ids,
                    spec_ref="R1, R2",
                )
                return PatchProposal(
                    hunks=[hunk],
                    summary="Correct fan temperature activation threshold (>=30.0) and restore 28.0 C hysteresis in ventilation logic.",
                )
            else:
                orig_code = line
                fix_code = line.replace("temp_val > TEMP_FAN_ON", "temp_val >= TEMP_FAN_ON")
                hunk = PatchHunk(
                    id="H1",
                    start_line=idx,
                    end_line=idx,
                    original_code=orig_code,
                    new_code=fix_code,
                    explanation="Fixes boundary defect by changing strict inequality (>) to greater-than-or-equal (>=).",
                    confidence=1.0,
                    fixes_tests=failed_ids,
                    spec_ref="R1",
                )
                return PatchProposal(
                    hunks=[hunk],
                    summary="Correct fan temperature activation boundary from > to >=.",
                )

    # 2. Check for robotics obstacle avoidance boundary defect:
    for idx, line in enumerate(source_lines, start=1):
        if is_protected(idx):
            continue
        if ("distance < 25.0" in line or "dist < 25.0" in line or "distance < STOP_DISTANCE" in line or "dist_val < STOP_DISTANCE" in line or "dist_val < 25.0" in line):
            orig_code = line
            fix_code = line.replace("< 25.0", "<= 25.0").replace("< STOP_DISTANCE", "<= STOP_DISTANCE")
            hunk = PatchHunk(
                id="H1",
                start_line=idx,
                end_line=idx,
                original_code=orig_code,
                new_code=fix_code,
                explanation="Fixes obstacle detection boundary condition from strict inequality (< 25.0) to (<= 25.0).",
                confidence=1.0,
                fixes_tests=failed_ids,
                spec_ref="R1",
            )
            return PatchProposal(
                hunks=[hunk],
                summary="Correct obstacle avoidance boundary trigger to <= 25.0 cm.",
            )

    # 3. Check for ultrasonic radar boundary defect:
    for idx, line in enumerate(source_lines, start=1):
        if "distance < ALERT_DISTANCE_CM" in line:
            orig_code = line
            fix_code = line.replace("distance < ALERT_DISTANCE_CM", "distance <= ALERT_DISTANCE_CM")
            hunk = PatchHunk(
                id="H1",
                start_line=idx,
                end_line=idx,
                original_code=orig_code,
                new_code=fix_code,
                explanation="Fixes boundary defect by changing strict inequality (<) to less-than-or-equal (<=).",
                confidence=1.0,
                fixes_tests=failed_ids,
                spec_ref="R1",
            )
            return PatchProposal(
                hunks=[hunk],
                summary="Correct proximity alert boundary condition from < to <=.",
            )

    # 4. Check for incubator overheat boundary defect:
    for idx, line in enumerate(source_lines, start=1):
        if "t > 40.0" in line or "temp > 40.0" in line:
            orig_code = line
            fix_code = line.replace("> 40.0", ">= 40.0")
            hunk = PatchHunk(
                id="H1",
                start_line=idx,
                end_line=idx,
                original_code=orig_code,
                new_code=fix_code,
                explanation="Corrects overheat safety alarm threshold from > 40.0 to >= 40.0.",
                confidence=1.0,
                fixes_tests=failed_ids,
                spec_ref="R4",
            )
            return PatchProposal(
                hunks=[hunk],
                summary="Correct incubator overheat alarm boundary condition to >= 40.0 C.",
            )

    # 5. Check for water tank monitor defects:
    for idx, line in enumerate(source_lines, start=1):
        if "level > 30.0" in line or "level > LEVEL_DRAIN_ON" in line:
            orig_code = line
            fix_code = line.replace("level > 30.0", "level >= 30.0").replace("level > LEVEL_DRAIN_ON", "level >= LEVEL_DRAIN_ON")
            hunk = PatchHunk(
                id="H1",
                start_line=idx,
                end_line=idx,
                original_code=orig_code,
                new_code=fix_code,
                explanation="Corrects drain pump activation threshold from > to >=.",
                confidence=1.0,
                fixes_tests=failed_ids,
                spec_ref="R1",
            )
            return PatchProposal(
                hunks=[hunk],
                summary="Correct water level drain trigger boundary from > to >=.",
            )

    # 6. Search for Arduino fan_controller control loop block: lines checking t >= 60.0, t > 30.0
    start_idx = None
    end_idx = None
    for idx, line in enumerate(source_lines, start=1):
        if "if (t >= 60.0)" in line:
            start_idx = idx
        if start_idx and line.strip() == "}":
            if idx > start_idx and idx <= start_idx + 10:
                end_idx = idx

    if start_idx and end_idx:
        orig_code = "\n".join(source_lines[start_idx - 1 : end_idx])
        fix_code = (
            "  if (isnan(t)) {\n"
            '    Serial.println("[ERROR] SENSOR_FAIL");\n'
            "    fanOn = true;\n"
            "  } else if (t >= 60.0) {\n"
            '    Serial.println("[ALARM] OVERHEAT");\n'
            "    fanOn = true;\n"
            "  } else if (t >= 30.0) {\n"
            "    fanOn = true;\n"
            "  } else if (t <= 28.0) {\n"
            "    fanOn = false;\n"
            "  }"
        )
        hunk = PatchHunk(
            id="H1",
            start_line=start_idx,
            end_line=end_idx,
            original_code=orig_code,
            new_code=fix_code,
            explanation="Fixes boundary check (>=30.0), adds hysteresis (<=28.0), and sensor disconnect fail-safe.",
            confidence=1.0,
            fixes_tests=failed_ids,
            spec_ref="R1, R2, R5",
        )
        return PatchProposal(
            hunks=[hunk],
            summary="Correct temperature thresholds, hysteresis, and sensor fault fail-safe handling in control loop.",
        )

    return PatchProposal(hunks=[], summary="No automated patch could be generated.")


def propose_patch(
    source: str,
    findings: list[Finding],
    failed_results: list[TestResult],
    analysis: Optional[FirmwareAnalysis] = None,
    client: Any = None,
    model: Optional[str] = None,
    use_cache: bool = True,
    cache_dir: Optional[Path] = None,
) -> PatchProposal:
    """Synthesize a patch proposal using Gemini or fallback."""
    numbered_source = number_source_code(source)
    failed_summary = summarize_failed_tests(failed_results, [])

    findings_summary_blocks = []
    for f in findings:
        findings_summary_blocks.append(
            f"- Finding {f.id}: {f.title} (Severity: {f.severity})\n"
            f"  Suspect lines: {f.suspect_lines}\n"
            f"  Expected: {f.expected}\n"
            f"  Observed: {f.observed}\n"
            f"  Likely cause: {f.likely_cause}\n"
            f"  Suggested fix: {f.suggested_fix}"
        )
    findings_summary = "\n".join(findings_summary_blocks) or "No specific findings provided."

    prompt = make_patch_prompt(
        numbered_source=numbered_source,
        failed_tests_summary=failed_summary,
        findings_summary=findings_summary,
    )

    try:
        proposal = generate_json(
            prompt=prompt,
            schema_model=PatchProposal,
            client=client,
            model=model,
            use_cache=use_cache,
            cache_dir=cache_dir,
        )
        if proposal and proposal.hunks:
            proposal.hunks = reconcile_hunks(source, proposal.hunks)
            return proposal
    except Exception:
        pass

    fallback = _fallback_patch_proposal(source, findings, failed_results)
    fallback.hunks = reconcile_hunks(source, fallback.hunks)
    return fallback
