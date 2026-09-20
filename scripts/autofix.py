"""Interactive CLI workflow for autonomous firmware bug-fixing."""

import argparse
import json
from pathlib import Path
import shutil
import sys

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.compare import format_comparison_summary, update_reports_with_fix
from agent.fixer import run_autofix, verify_fix
from agent.models import FixAttempt, TestResult
from agent.patcher import apply_to_original, revert_original


def find_latest_run_id(runs_dir: Path) -> str:
    """Find the most recently created or modified run ID under runs/."""
    candidates = [
        d
        for d in runs_dir.iterdir()
        if d.is_dir() and d.name not in ("cache", "golden")
    ]
    if not candidates:
        raise FileNotFoundError("No run directories found under runs/.")
    latest = max(candidates, key=lambda d: d.stat().st_mtime)
    return latest.name


def handle_revert(run_id: str, runs_base_dir: Path, firmware_dir: Path) -> int:
    """Restore original main.cpp from backup."""
    fix_base = runs_base_dir / run_id / "fix"
    orig_file = firmware_dir / "src" / "main.cpp"
    local_bak = firmware_dir / "src" / "main.cpp.bak"

    attempt: FixAttempt | None = None
    if fix_base.is_dir():
        # Find attempt directories
        attempt_dirs = sorted(
            [d for d in fix_base.iterdir() if d.is_dir()],
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )
        for att_dir in attempt_dirs:
            att_file = att_dir / "attempt.json"
            if att_file.is_file():
                try:
                    data = json.loads(att_file.read_text(encoding="utf-8"))
                    attempt = FixAttempt.model_validate(data)
                    break
                except Exception:
                    continue

    if attempt is not None:
        try:
            revert_original(
                attempt,
                run_id,
                firmware_dir=firmware_dir,
                runs_base_dir=runs_base_dir,
            )
            print(f"[REVERT] Successfully reverted {orig_file} to backup.")
            return 0
        except Exception as exc:
            print(f"[REVERT ERROR] Failed to revert using attempt {attempt.attempt_id}: {exc}")

    # Fallback to local main.cpp.bak if available
    if local_bak.is_file():
        tmp_file = orig_file.with_suffix(".tmp")
        shutil.copy2(local_bak, tmp_file)
        import os
        os.replace(tmp_file, orig_file)
        print(f"[REVERT] Successfully restored {orig_file} from {local_bak}.")
        return 0

    print(f"[ERROR] No backup found to revert for run '{run_id}'.")
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Autonomous firmware bug fix CLI."
    )
    parser.add_argument(
        "run_id",
        nargs="?",
        default=None,
        help="Run ID under runs/ (e.g. dev or timestamped run)",
    )
    parser.add_argument(
        "--run-id",
        dest="run_id_opt",
        type=str,
        default=None,
        help="Run ID (option form)",
    )
    parser.add_argument(
        "--revert",
        action="store_true",
        help="Undo fix and restore original main.cpp from backup",
    )
    parser.add_argument(
        "--firmware-dir",
        type=str,
        default="firmware/fan_controller",
        help="Target firmware project directory",
    )
    parser.add_argument(
        "--runs-dir",
        type=str,
        default="runs",
        help="Runs base directory",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Auto-confirm all interactive prompts",
    )

    args = parser.parse_args()
    runs_base_dir = Path(args.runs_dir).resolve()
    firmware_dir = Path(args.firmware_dir).resolve()

    run_id = args.run_id or args.run_id_opt
    if not run_id:
        try:
            run_id = find_latest_run_id(runs_base_dir)
            print(f"No run_id specified. Using latest run: {run_id}")
        except Exception as exc:
            print(f"[ERROR] {exc}")
            sys.exit(1)

    if args.revert:
        code = handle_revert(run_id, runs_base_dir, firmware_dir)
        sys.exit(code)

    run_dir = runs_base_dir / run_id
    if not run_dir.is_dir():
        print(f"[ERROR] Run directory not found: {run_dir}")
        sys.exit(1)

    results_file = run_dir / "results.json"
    if results_file.is_file():
        results = [
            TestResult.model_validate(r)
            for r in json.loads(results_file.read_text(encoding="utf-8"))
        ]
        failed = [r for r in results if r.status in ("FAIL", "ERROR")]
        if not failed:
            print(f"All {len(results)} tests in run '{run_id}' passed. No fix needed!")
            sys.exit(0)

    print(f"\n============================================================")
    print(f"  FIRMWARE AUTO-FIX: [{run_id}]")
    print(f"============================================================\n")

    # Step b: Propose and validate patch
    print("[1/4] Analyzing root causes and generating patch proposal...")
    attempt = run_autofix(
        run_id=run_id,
        runs_base_dir=runs_base_dir,
        firmware_dir=firmware_dir,
    )

    print(f"\nPatch Summary: {attempt.proposal.summary}")
    print(f"Hunks Proposed: {len(attempt.proposal.hunks)}\n")

    diff_file = runs_base_dir / run_id / "fix" / attempt.attempt_id / "diff.patch"
    diff_text = (
        diff_file.read_text(encoding="utf-8") if diff_file.is_file() else ""
    )

    print("----- PROPOSED DIFF -----")
    print(diff_text.strip() or "(No diff)")
    print("-------------------------\n")

    print("Validation checks:")
    for check in attempt.validation.checks:
        symbol = "✓" if check.ok else "✗"
        print(f"  [{symbol}] {check.name}: {check.detail}")

    if not attempt.validation.ok:
        print(f"\n[ERROR] Patch validation failed. Fix attempt rejected.")
        sys.exit(1)

    # Step c: Ask user to verify on sandbox copy
    if not args.yes:
        confirm = input("\nAttempt fix in sandbox copy? [Y/n]: ").strip().lower()
        if confirm in ("n", "no"):
            print("Aborted by user.")
            sys.exit(0)

    # Step d: Re-run failed tests + regression check on sandbox copy
    print("\n[2/4] Verifying fix on sandbox copy (re-running failed tests + regression suite)...")
    attempt = verify_fix(
        attempt=attempt,
        run_id=run_id,
        runs_base_dir=runs_base_dir,
    )

    # Step e: Show comparison summary
    print("\n[3/4] Verification outcome:")
    print(format_comparison_summary(attempt))

    # Update report.md and report.html with before vs after section
    update_reports_with_fix(run_id, attempt, diff_text, runs_base_dir)

    # Step f: If verified with 0 regressions, ask to apply to original
    if attempt.status == "rejected":
        print(f"\n[RESULT] Fix auto-rejected: regressions detected or 0 tests fixed.")
        sys.exit(1)

    if len(attempt.regressions) == 0 and len(attempt.fixed_tests) > 0:
        print(f"\n[4/4] Fix verified successfully! ({len(attempt.fixed_tests)} tests fixed, 0 regressions)")
        if not args.yes:
            apply_confirm = input("\nApply to original firmware? [y/N]: ").strip().lower()
            should_apply = apply_confirm in ("y", "yes")
        else:
            should_apply = True

        if should_apply:
            orig = apply_to_original(
                attempt=attempt,
                run_id=run_id,
                firmware_dir=firmware_dir,
                runs_base_dir=runs_base_dir,
            )
            print(f"\n[APPLIED] Successfully patched original firmware: {orig}")
            print(f"To undo: python scripts/autofix.py {run_id} --revert\n")
        else:
            print("\nOriginal firmware unchanged. Sandbox fix remains under:")
            print(f"  {runs_base_dir / run_id / 'fix' / attempt.attempt_id}")
    else:
        print("\nFix did not meet criteria for application.")


if __name__ == "__main__":
    main()
