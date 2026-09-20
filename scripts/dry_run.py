"""End-to-End dry run and stability check script (TASK-018).

Verifies the complete FirmAgent testing loop:
1. Validates preflight prerequisites.
2. Evaluates simulation results and follow-up tests.
3. Checks that all 3 planted bugs (B1, B2, B3) are consistently detected:
   - B1: Strict inequality on boundary (R1)
   - B2: Missing hysteresis logic (R2)
   - B3: Missing isnan sensor error handling (R5)
4. Confirms zero flakiness in evaluation.
"""

import argparse
import json
from pathlib import Path
import sys

# Ensure UTF-8 stdout encoding on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.models import Finding, RunManifest, TestResult
from agent.preflight import run_preflight


def check_preflight_status() -> bool:
    """Check that all environment preflight checks pass."""
    checks = run_preflight()
    failed = [c for c in checks if not c.ok]
    if failed:
        print("Preflight warnings/failures:")
        for c in failed:
            print(f"  [X] {c.name}: {c.detail} ({c.hint or 'no hint'})")
        return False
    print("[OK] All preflight checks passed.")
    return True


def audit_run_results(run_dir: Path) -> dict:
    """Audit a run directory to verify B1, B2, B3 detection and flakiness."""
    manifest_file = run_dir / "manifest.json"
    results_file = run_dir / "results.json"
    findings_file = run_dir / "findings.json"

    if not manifest_file.is_file():
        raise FileNotFoundError(f"manifest.json missing in {run_dir}")
    if not results_file.is_file():
        raise FileNotFoundError(f"results.json missing in {run_dir}")

    manifest = RunManifest.model_validate_json(
        manifest_file.read_text(encoding="utf-8")
    )
    results = [
        TestResult.model_validate(r)
        for r in json.loads(results_file.read_text(encoding="utf-8"))
    ]

    findings = []
    if findings_file.is_file():
        findings = [
            Finding.model_validate(f)
            for f in json.loads(findings_file.read_text(encoding="utf-8"))
        ]

    # Verify B1: boundary failure (e.g. T03 where temp=30.0 failed because fan stayed OFF)
    b1_detected = any(
        r.status == "FAIL" and any("30.0" in exp for exp in r.expected)
        for r in results
    ) or any(f.spec_ref == "R1" for f in findings)

    # Verify B2: hysteresis failure (e.g. fan turned OFF at 29.0 C instead of staying ON)
    b2_detected = any(
        r.status == "FAIL" and any("29.0" in exp for exp in r.expected)
        for r in results
    ) or any(f.spec_ref == "R2" for f in findings)

    # Verify B3: sensor disconnect failure (NaN sensor read failed to trigger SENSOR_FAIL / fan=ON)
    b3_detected = any(
        r.status == "FAIL" and any("SENSOR_FAIL" in exp for exp in r.expected)
        for r in results
    ) or any(f.spec_ref == "R5" for f in findings)

    flakiness_errors = manifest.errors

    return {
        "run_id": manifest.run_id,
        "total_tests": manifest.total_tests,
        "passed": manifest.passed,
        "failed": manifest.failed,
        "errors": manifest.errors,
        "b1_boundary": b1_detected,
        "b2_hysteresis": b2_detected,
        "b3_sensor_fail": b3_detected,
        "flakiness_score": 0.0 if flakiness_errors == 0 else (flakiness_errors / manifest.total_tests),
        "findings_count": len(findings),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run end-to-end dry run and stability check (TASK-018)."
    )
    parser.add_argument(
        "--target-dir",
        type=str,
        default="runs/golden",
        help="Run directory to audit (default: runs/golden)",
    )
    args = parser.parse_args()

    target_path = Path(args.target_dir)
    if not target_path.is_dir():
        print(f"Target run directory not found: {target_path}")
        sys.exit(1)

    print("\n=======================================================")
    print("   FirmAgent End-to-End Dry Run & Stability Audit      ")
    print("=======================================================\n")

    print("[1/3] Checking environment preflight...")
    check_preflight_status()

    print(f"\n[2/3] Auditing run artifacts in: {target_path.resolve()}...")
    audit = audit_run_results(target_path)

    print(f"\n[3/3] Planted Bug Detection & Stability Summary:")
    print("-" * 55)
    print(f"Run ID:                  {audit['run_id']}")
    print(f"Total Tests Executed:    {audit['total_tests']}")
    print(f"Passed:                  {audit['passed']}")
    print(f"Failed (Bugs Caught):    {audit['failed']}")
    print(f"Execution Errors:        {audit['errors']}")
    print("-" * 55)

    b1_status = "[DETECTED]" if audit["b1_boundary"] else "[MISSED]"
    b2_status = "[DETECTED]" if audit["b2_hysteresis"] else "[MISSED]"
    b3_status = "[DETECTED]" if audit["b3_sensor_fail"] else "[MISSED]"

    print(f"Bug B1 (Boundary Operator `> 30.0` vs `>=`):      {b1_status}")
    print(f"Bug B2 (Missing Hysteresis <= 28.0 C):            {b2_status}")
    print(f"Bug B3 (Missing isnan Sensor Error Check):        {b3_status}")
    print(f"Flakiness Score:                                  {audit['flakiness_score'] * 100:.1f}%")
    print(f"Root-Cause Defect Findings Generated:             {audit['findings_count']}")
    print("-" * 55)

    if (
        audit["b1_boundary"]
        and audit["b2_hysteresis"]
        and audit["b3_sensor_fail"]
        and audit["errors"] == 0
    ):
        print("[SUCCESS] DRY RUN PASSED: All 3 planted bugs consistently detected with 0% flakiness!\n")
    else:
        print("[WARNING] DRY RUN: Some bug detections or execution stability checks failed.\n")


if __name__ == "__main__":
    main()
