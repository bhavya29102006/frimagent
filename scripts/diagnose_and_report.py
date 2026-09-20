"""CLI script to run root-cause analysis and generate Markdown/HTML reports on a run directory."""

import argparse
import os
from pathlib import Path
import sys

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.reporter import generate_reports
from agent.rootcause import run_root_cause


def find_latest_run_dir() -> Path:
    """Find the most recently modified run folder in runs/."""
    runs_dir = PROJECT_ROOT / "runs"
    if not runs_dir.is_dir():
        raise FileNotFoundError("runs/ directory not found.")

    candidates = [
        d
        for d in runs_dir.iterdir()
        if d.is_dir() and d.name not in ("cache", "dev", "golden")
    ]
    if not candidates:
        # Fall back to runs/dev if no dynamic runs exist
        dev_dir = runs_dir / "dev"
        if dev_dir.is_dir():
            return dev_dir
        raise FileNotFoundError("No run folders found under runs/.")

    return max(candidates, key=lambda d: d.stat().st_mtime)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Diagnose failed tests and generate test reports."
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Run ID to diagnose (under runs/<run-id>)",
    )
    parser.add_argument(
        "--run-dir",
        type=str,
        default=None,
        help="Direct path to run directory",
    )
    parser.add_argument(
        "--firmware-source",
        type=str,
        default=None,
        help="Path to firmware source code file",
    )

    args = parser.parse_args()

    if args.run_dir:
        target_dir = Path(args.run_dir)
    elif args.run_id:
        target_dir = PROJECT_ROOT / "runs" / args.run_id
    else:
        target_dir = find_latest_run_dir()

    if not target_dir.is_dir():
        print(f"Error: Target run directory not found: {target_dir}")
        sys.exit(1)

    print(f"\n=== FirmAgent Root Cause & Report Generator ===")
    print(f"Target Run: {target_dir.name} ({target_dir.resolve()})\n")

    # Step 1: Root Cause Analysis
    print("Running root-cause diagnosis on failed tests...")
    try:
        findings = run_root_cause(
            run_dir=target_dir,
            firmware_source_path=args.firmware_source,
        )
        print(f"Identified {len(findings)} root-cause defect(s):")
        for f in findings:
            sev_color = f.severity.upper()
            lines_info = (
                f"(lines: {f.suspect_lines})" if f.suspect_lines else ""
            )
            print(f"  [{f.id}] [{sev_color}] {f.title} {lines_info}")
            print(f"       Failed tests: {f.failed_tests}")
            print(f"       Likely cause: {f.likely_cause}")
    except Exception as exc:
        print(f"Warning: Root cause analysis encountered an error: {exc}")

    # Step 2: Generate Reports
    print("\nGenerating Markdown and HTML reports...")
    try:
        md_path, html_path = generate_reports(
            run_dir=target_dir,
            firmware_source_path=args.firmware_source,
        )
        print(f"Markdown report generated: {md_path.resolve()}")
        print(f"HTML report generated:     {html_path.resolve()}\n")
    except Exception as exc:
        print(f"Error generating reports: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
