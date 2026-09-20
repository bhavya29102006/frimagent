"""CLI script to run all simulation tests autonomously with live progress and summary table."""

import argparse
import json
import os
from pathlib import Path
import sys

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.orchestrator import run_all

# Enable ANSI escape sequences on Windows console
if sys.platform == "win32":
    os.system("")

COLOR_GREEN = "\033[92m"
COLOR_RED = "\033[91m"
COLOR_YELLOW = "\033[93m"
COLOR_CYAN = "\033[96m"
COLOR_BOLD = "\033[1m"
COLOR_RESET = "\033[0m"


def colorize_status(status: str) -> str:
    if status == "PASS":
        return f"{COLOR_GREEN}{status}{COLOR_RESET}"
    if status == "FAIL":
        return f"{COLOR_RED}{status}{COLOR_RESET}"
    return f"{COLOR_YELLOW}{status}{COLOR_RESET}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run firmware simulation tests autonomously."
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help="Optional comma-separated list of test IDs (e.g. --only T01,T03)",
    )
    parser.add_argument(
        "--source-dir",
        type=str,
        default="runs/dev",
        help="Directory containing analysis.json and tests.json (default: runs/dev)",
    )
    parser.add_argument(
        "--firmware-dir",
        type=str,
        default="firmware/fan_controller",
        help="Firmware project directory (default: firmware/fan_controller)",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Optional custom run ID",
    )

    args = parser.parse_args()

    print(f"\n{COLOR_BOLD}=== FirmAgent Autonomous Test Runner ==={COLOR_RESET}")
    print(f"Firmware:   {args.firmware_dir}")
    print(f"Source:     {args.source_dir}")
    if args.only:
        print(f"Filter:     only running {args.only}")
    print("Starting simulation test execution...\n")

    def handle_event(event: dict) -> None:
        event_type = event.get("type")
        if event_type == "test_finished":
            idx = event.get("index")
            total = event.get("total")
            t_id = event.get("test_id")
            res = event.get("result")
            status = res.status if res else "ERROR"
            dur = res.duration_s if res else 0.0
            print(f"[{idx}/{total}] {t_id} {colorize_status(status)} {dur:.1f}s")

    manifest = run_all(
        run_id=args.run_id,
        source_dir=args.source_dir,
        firmware_dir=args.firmware_dir,
        on_event=handle_event,
        only_ids=args.only,
    )

    run_dir = Path("runs") / manifest.run_id
    tests_file = run_dir / "tests.json"
    results_file = run_dir / "results.json"

    test_meta: dict[str, dict[str, str]] = {}
    if tests_file.is_file():
        raw = json.loads(tests_file.read_text(encoding="utf-8"))
        tests_list = raw.get("tests", []) if isinstance(raw, dict) else raw
        for t in tests_list:
            test_meta[t.get("id", "")] = {
                "name": t.get("name", ""),
                "category": t.get("category", ""),
            }

    results = []
    if results_file.is_file():
        results = json.loads(results_file.read_text(encoding="utf-8"))

    # Print summary table
    print(f"\n{COLOR_BOLD}=== Execution Summary ({manifest.run_id}) ==={COLOR_RESET}")
    header = f"{'ID':<6} {'Name':<42} {'Category':<16} {'Status':<18} {'Duration':<10}"
    separator = "-" * 92
    print(separator)
    print(header)
    print(separator)

    for r in results:
        t_id = r.get("test_id", "")
        meta = test_meta.get(t_id, {})
        name = meta.get("name", t_id)
        if len(name) > 40:
            name = name[:37] + "..."
        cat = meta.get("category", "")
        status = r.get("status", "")
        dur = f"{r.get('duration_s', 0.0):.1f}s"
        status_col = colorize_status(status)
        # Pad status_col considering ANSI codes (approx 9 visible chars)
        pad = " " * (10 - len(status))
        print(f"{t_id:<6} {name:<42} {cat:<16} {status_col}{pad} {dur:<10}")

    print(separator)
    print(
        f"{COLOR_BOLD}Total:{COLOR_RESET} {manifest.total_tests} | "
        f"{COLOR_GREEN}Passed:{COLOR_RESET} {manifest.passed} | "
        f"{COLOR_RED}Failed:{COLOR_RESET} {manifest.failed} | "
        f"{COLOR_YELLOW}Errors:{COLOR_RESET} {manifest.errors} | "
        f"Status: {manifest.status}"
    )
    print(f"Results saved to: {run_dir.resolve()}\n")


if __name__ == "__main__":
    main()
