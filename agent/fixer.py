"""Auto-fix orchestrator: sandbox workspace preparation, proposal, multi-stage validation, and regression verification."""

from datetime import datetime
import json
import os
from pathlib import Path
import shutil
from typing import Any, Callable, Optional

from agent.builder import build_firmware
from agent.models import (
    Finding,
    FirmwareAnalysis,
    FixAttempt,
    PatchProposal,
    PatchValidation,
    TestResult,
)
from agent.orchestrator import run_all
from agent.patcher import (
    _fallback_patch_proposal,
    apply_patch_to_copy,
    find_patch_target_file,
    propose_patch,
    render_diff,
    validate_patch,
)


def prepare_fix_workspace(
    run_id: str,
    attempt_id: str,
    firmware_dir: Path | str = "firmware/fan_controller",
    runs_base_dir: Path | str = "runs",
) -> Path:
    """Copy target firmware into a dedicated sandbox workspace: runs/<run_id>/fix/<attempt_id>/project/.

    Includes .pio directory if present to preserve cached PlatformIO tools and libraries.
    """
    fw_path = Path(firmware_dir).resolve()
    fix_dir = Path(runs_base_dir) / run_id / "fix" / attempt_id
    project_copy = fix_dir / "project"
    if project_copy.is_dir():
        shutil.rmtree(project_copy, ignore_errors=True)
    project_copy.mkdir(parents=True, exist_ok=True)

    for item in fw_path.iterdir():
        dest = project_copy / item.name
        if item.is_dir():
            if not dest.exists():
                shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)

    # Normalize newlines in all copied source files to prevent CRCRLF doubling
    for ext in ("*.cpp", "*.c", "*.py", "*.ino", "*.h"):
        for src_f in project_copy.rglob(ext):
            try:
                txt = src_f.read_text(encoding="utf-8", errors="ignore")
                clean = txt.replace("\r\r\n", "\n").replace("\r\n", "\n").replace("\r", "\n")
                src_f.write_text(clean, encoding="utf-8", newline="\n")
            except Exception:
                pass

    return project_copy


def run_autofix(
    run_id: str,
    runs_base_dir: Path | str = "runs",
    firmware_dir: Path | str = "firmware/fan_controller",
    attempt_id: Optional[str] = None,
    client: Any = None,
    model: Optional[str] = None,
) -> FixAttempt:
    """Load run artifacts, propose a patch, validate it on a sandbox copy, and return for preview.

    Saves proposal.json, validation.json, diff.patch, and attempt.json under:
    runs/<run_id>/fix/<attempt_id>/
    """
    base_dir = Path(runs_base_dir)
    run_dir = base_dir / run_id
    if attempt_id is None:
        attempt_id = f"att-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    fix_dir = run_dir / "fix" / attempt_id
    fix_dir.mkdir(parents=True, exist_ok=True)

    manifest_file = run_dir / "manifest.json"
    if manifest_file.is_file():
        try:
            m_data = json.loads(manifest_file.read_text(encoding="utf-8"))
            fw_n = m_data.get("firmware_name")
            if fw_n and (Path("firmware") / fw_n).is_dir():
                firmware_dir = Path("firmware") / fw_n
        except Exception:
            pass

    # 1. Load run artifacts
    results_file = run_dir / "results.json"
    findings_file = run_dir / "findings.json"
    analysis_file = run_dir / "analysis.json"
    source_file = run_dir / "firmware_source.txt"
    if not source_file.is_file():
        source_file = find_patch_target_file(firmware_dir)

    results_raw = (
        json.loads(results_file.read_text(encoding="utf-8"))
        if results_file.is_file()
        else []
    )
    results = [TestResult.model_validate(r) for r in results_raw]

    findings_raw = (
        json.loads(findings_file.read_text(encoding="utf-8"))
        if findings_file.is_file()
        else []
    )
    findings = [Finding.model_validate(f) for f in findings_raw]

    analysis = None
    if analysis_file.is_file():
        analysis = FirmwareAnalysis.model_validate(
            json.loads(analysis_file.read_text(encoding="utf-8"))
        )

    source_code = (
        source_file.read_text(encoding="utf-8").replace("\r\r\n", "\n").replace("\r\n", "\n").replace("\r", "\n")
        if source_file.is_file()
        else ""
    )

    # 2. Calculate baseline counts
    failed_res = [r for r in results if r.status in ("FAIL", "ERROR")]
    passed_res = [r for r in results if r.status == "PASS"]
    before_counts = {
        "total": len(results),
        "passed": len(passed_res),
        "failed": len([r for r in results if r.status == "FAIL"]),
        "errors": len([r for r in results if r.status == "ERROR"]),
    }

    # 3. Create sandbox copy
    copy_dir = prepare_fix_workspace(
        run_id=run_id,
        attempt_id=attempt_id,
        firmware_dir=firmware_dir,
        runs_base_dir=runs_base_dir,
    )

    # 4. Propose patch
    proposal = propose_patch(
        source=source_code,
        findings=findings,
        failed_results=failed_res,
        analysis=analysis,
        client=client,
        model=model,
        cache_dir=run_dir / "cache",
    )

    # 5. Validate patch on the copy (including PlatformIO compilation)
    validation = validate_patch(
        source=source_code,
        proposal=proposal,
        findings=findings,
        project_copy_dir=copy_dir,
    )

    # If proposal failed validation, automatically try fallback patch proposal so user is never blocked
    if not validation.ok:
        fallback_prop = _fallback_patch_proposal(source_code, findings, failed_res)
        if fallback_prop and fallback_prop.hunks:
            fallback_val = validate_patch(
                source=source_code,
                proposal=fallback_prop,
                findings=findings,
                project_copy_dir=copy_dir,
            )
            if fallback_val.ok:
                proposal = fallback_prop
                validation = fallback_val

    # 6. Render unified diff
    diff_text = render_diff(source_code, proposal)

    status = "validated" if validation.ok else "rejected"
    attempt = FixAttempt(
        attempt_id=attempt_id,
        status=status,
        proposal=proposal,
        validation=validation,
        before_counts=before_counts,
        after_counts=None,
        fixed_tests=[],
        regressions=[],
    )

    # 7. Persist artifacts
    (fix_dir / "proposal.json").write_text(
        proposal.model_dump_json(indent=2), encoding="utf-8"
    )
    (fix_dir / "validation.json").write_text(
        validation.model_dump_json(indent=2), encoding="utf-8"
    )
    (fix_dir / "diff.patch").write_text(diff_text, encoding="utf-8")
    (fix_dir / "attempt.json").write_text(
        attempt.model_dump_json(indent=2), encoding="utf-8"
    )

    return attempt


def verify_fix(
    attempt: FixAttempt,
    run_id: str,
    runs_base_dir: Path | str = "runs",
    runner_fn: Optional[Callable[..., TestResult]] = None,
    builder_fn: Optional[Callable[..., tuple[bool, str, dict[str, Path]]]] = None,
    stop_event: Any = None,
    on_step: Optional[Callable[[str], None]] = None,
    simulator_name: Optional[str] = None,
) -> FixAttempt:
    """Verify a proposed fix on the sandbox copy and auto-reject if build fails or regressions occur.

    Steps:
    1. Compile the sandbox copy.
    2. Re-run ONLY the failed test IDs on the copy.
    3. Re-run the previously passing test IDs on the copy as a regression check.
    4. Compute fixed tests, regressions, and after_counts.
    5. Auto-reject if:
       - Build fails, OR
       - A regression appears (>= 1 previously passing test fails), OR
       - Zero failed tests got fixed.
    6. Saves attempt.json and results_after.json under runs/<run_id>/fix/<attempt_id>/.
    """
    fix_dir = Path(runs_base_dir) / run_id / "fix" / attempt.attempt_id
    copy_dir = fix_dir / "project"
    run_dir = Path(runs_base_dir) / run_id

    # Ensure sandbox project copy exists and has files; if not, prepare it now
    if not copy_dir.is_dir() or not any(copy_dir.iterdir()):
        fw_dir = Path("firmware/fan_controller")
        manifest_file = run_dir / "manifest.json"
        if manifest_file.is_file():
            try:
                m_data = json.loads(manifest_file.read_text(encoding="utf-8"))
                fw_n = m_data.get("firmware_name")
                if fw_n and (Path("firmware") / fw_n).is_dir():
                    fw_dir = Path("firmware") / fw_n
            except Exception:
                pass
        prepare_fix_workspace(
            run_id=run_id,
            attempt_id=attempt.attempt_id,
            firmware_dir=fw_dir,
            runs_base_dir=runs_base_dir,
        )

    # Resolve simulator engine from parameter, manifest, or infer from project files
    sim_name = simulator_name
    if not sim_name:
        manifest_file = run_dir / "manifest.json"
        if manifest_file.is_file():
            try:
                m_data = json.loads(manifest_file.read_text(encoding="utf-8"))
                sim_name = m_data.get("simulator_name")
            except Exception:
                pass
    if not sim_name:
        # Detect simulator from project files
        is_robot = (copy_dir / "model.sdf").is_file() or ((run_dir / "manifest.json").is_file() and "robot" in (run_dir / "manifest.json").read_text(encoding="utf-8"))
        is_py = (any((copy_dir / "src").glob("*.py")) if (copy_dir / "src").is_dir() else False) or any(copy_dir.glob("*.py"))
        is_c = (copy_dir / "src" / "main.c").is_file() or (any((copy_dir / "src").glob("*.c")) if (copy_dir / "src").is_dir() else False) or any(copy_dir.glob("*.c"))
        if is_robot:
            sim_name = "gazebo"
        elif is_py:
            sim_name = "python_sim"
        elif is_c:
            sim_name = "native_c"
        else:
            sim_name = "virtual_mock"

    # 1. Load baseline results
    results_file = run_dir / "results.json"
    results_raw = (
        json.loads(results_file.read_text(encoding="utf-8"))
        if results_file.is_file()
        else []
    )
    results = [TestResult.model_validate(r) for r in results_raw]

    failed_ids = [r.test_id for r in results if r.status in ("FAIL", "ERROR")]
    passed_ids = [r.test_id for r in results if r.status == "PASS"]

    # 2. Apply patch to copy
    apply_patch_to_copy(copy_dir, attempt.proposal)

    # 3. Build the copy
    if on_step:
        on_step("build")
    build_func = builder_fn if builder_fn is not None else build_firmware
    build_ok, log_tail, artifacts = build_func(copy_dir)

    if not build_ok:
        attempt.status = "rejected"
        (fix_dir / "attempt.json").write_text(
            attempt.model_dump_json(indent=2), encoding="utf-8"
        )
        return attempt

    if stop_event and getattr(stop_event, "is_set", lambda: False)():
        attempt.status = "rejected"
        (fix_dir / "attempt.json").write_text(
            attempt.model_dump_json(indent=2), encoding="utf-8"
        )
        return attempt

    # 4. Re-run failed tests on copy
    if on_step:
        on_step("retest_failed")
    run_all(
        run_id=f"{run_id}_fix_failed",
        source_dir=run_dir,
        firmware_dir=copy_dir,
        only_ids=failed_ids,
        runner_fn=runner_fn,
        runs_base_dir=fix_dir,
        stop_event=stop_event,
        simulator_name=sim_name,
    )

    if stop_event and getattr(stop_event, "is_set", lambda: False)():
        attempt.status = "rejected"
        (fix_dir / "attempt.json").write_text(
            attempt.model_dump_json(indent=2), encoding="utf-8"
        )
        return attempt

    # 5. Re-run passing tests on copy (regression check)
    if on_step:
        on_step("regression_check")
    run_all(
        run_id=f"{run_id}_fix_passed",
        source_dir=run_dir,
        firmware_dir=copy_dir,
        only_ids=passed_ids,
        runner_fn=runner_fn,
        runs_base_dir=fix_dir,
        stop_event=stop_event,
        simulator_name=sim_name,
    )

    # 6. Collect after results
    res_failed_file = fix_dir / f"{run_id}_fix_failed" / "results.json"
    res_passed_file = fix_dir / f"{run_id}_fix_passed" / "results.json"

    after_res_list: list[TestResult] = []
    if res_failed_file.is_file():
        after_res_list.extend(
            [
                TestResult.model_validate(r)
                for r in json.loads(res_failed_file.read_text(encoding="utf-8"))
            ]
        )
    if res_passed_file.is_file():
        after_res_list.extend(
            [
                TestResult.model_validate(r)
                for r in json.loads(res_passed_file.read_text(encoding="utf-8"))
            ]
        )

    after_status = {r.test_id: r.status for r in after_res_list}

    fixed_tests = [t for t in failed_ids if after_status.get(t) == "PASS"]
    regressions = [t for t in passed_ids if after_status.get(t) != "PASS"]

    after_counts = {
        "total": len(results),
        "passed": sum(1 for s in after_status.values() if s == "PASS"),
        "failed": sum(1 for s in after_status.values() if s == "FAIL"),
        "errors": sum(1 for s in after_status.values() if s == "ERROR"),
    }

    attempt.after_counts = after_counts
    attempt.fixed_tests = fixed_tests
    attempt.regressions = regressions

    # Auto-reject check:
    # Auto-reject if regressions > 0 or fixed_tests == 0
    if len(regressions) > 0 or len(fixed_tests) == 0:
        attempt.status = "rejected"
    else:
        attempt.status = "validated"

    # Save attempt.json and results_after.json
    (fix_dir / "attempt.json").write_text(
        attempt.model_dump_json(indent=2), encoding="utf-8"
    )
    (fix_dir / "results_after.json").write_text(
        json.dumps([r.model_dump() for r in after_res_list], indent=2),
        encoding="utf-8",
    )

    return attempt


def load_fix_attempt(
    run_id: str,
    runs_base_dir: Path | str = "runs",
    attempt_id: Optional[str] = None,
) -> Optional[FixAttempt]:
    """Load an existing FixAttempt from runs/<run_id>/fix/."""
    fix_base = Path(runs_base_dir) / run_id / "fix"
    if not fix_base.is_dir():
        return None

    # If attempt.json is directly in fix/
    direct_att = fix_base / "attempt.json"
    if direct_att.is_file():
        try:
            return FixAttempt.model_validate(json.loads(direct_att.read_text(encoding="utf-8")))
        except Exception:
            pass

    # If attempt_id specified
    if attempt_id:
        target = fix_base / attempt_id / "attempt.json"
        if target.is_file():
            try:
                return FixAttempt.model_validate(json.loads(target.read_text(encoding="utf-8")))
            except Exception:
                pass

    # Otherwise inspect attempt directories, newest first
    subdirs = sorted(
        [d for d in fix_base.iterdir() if d.is_dir()],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    for d in subdirs:
        att_file = d / "attempt.json"
        if att_file.is_file():
            try:
                return FixAttempt.model_validate(json.loads(att_file.read_text(encoding="utf-8")))
            except Exception:
                continue

    return None


def save_golden_fix_attempt(
    run_id: str,
    attempt: FixAttempt,
    runs_base_dir: Path | str = "runs",
) -> Path:
    """Export a verified fix attempt into runs/golden/fix/ for offline replay."""
    base_dir = Path(runs_base_dir).resolve()
    golden_fix_dir = base_dir / "golden" / "fix"
    golden_fix_dir.mkdir(parents=True, exist_ok=True)

    src_fix_dir = base_dir / run_id / "fix" / attempt.attempt_id
    if src_fix_dir.is_dir():
        for fname in ["attempt.json", "proposal.json", "validation.json", "diff.patch", "results_after.json"]:
            f = src_fix_dir / fname
            if f.is_file():
                shutil.copy2(f, golden_fix_dir / fname)
    else:
        (golden_fix_dir / "attempt.json").write_text(
            attempt.model_dump_json(indent=2), encoding="utf-8"
        )
        (golden_fix_dir / "proposal.json").write_text(
            attempt.proposal.model_dump_json(indent=2), encoding="utf-8"
        )
        (golden_fix_dir / "validation.json").write_text(
            attempt.validation.model_dump_json(indent=2), encoding="utf-8"
        )

    return golden_fix_dir
