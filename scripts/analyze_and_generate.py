"""Script to run analyzer and test generator on the demo firmware (TASK-006 & TASK-007).

Reads firmware/fan_controller/src/main.cpp,
runs analyzer then generator,
saves runs/dev/analysis.json and runs/dev/tests.json,
prints a readable summary.
"""

import argparse
from collections import Counter
from pathlib import Path
import sys

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.analyzer import analyze_firmware
from agent.coverage import compute_coverage
from agent.generator import generate_tests
from agent.models import TestList


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run analyzer and test generator on demo firmware."
    )
    parser.add_argument(
        "--out",
        type=str,
        default="runs/dev",
        help="Output directory (defaults to 'runs/dev', e.g. 'runs/dev_new')",
    )
    args = parser.parse_args()

    firmware_path = PROJECT_ROOT / "firmware" / "fan_controller" / "src" / "main.cpp"
    if not firmware_path.is_file():
        print(f"Error: Firmware file not found at {firmware_path}")
        sys.exit(1)

    out_path = Path(args.out)
    out_dir = out_path if out_path.is_absolute() else PROJECT_ROOT / out_path
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"1. Reading firmware: {firmware_path}")
    source_code = firmware_path.read_text(encoding="utf-8")

    print("2. Running Analyzer (TASK-006)...")
    analysis = analyze_firmware(source_code)

    analysis_file = out_dir / "analysis.json"
    analysis_file.write_text(analysis.model_dump_json(indent=2), encoding="utf-8")
    print(f"   Saved analysis to {analysis_file}")

    print("3. Running Test Generator (TASK-007 & TASK-020)...")
    tests = generate_tests(analysis, source_code)

    tests_file = out_dir / "tests.json"
    tests_file.write_text(
        TestList(tests=tests).model_dump_json(indent=2), encoding="utf-8"
    )
    print(f"   Saved {len(tests)} tests to {tests_file}")


    print("\n" + "=" * 60)
    print("ANALYSIS SUMMARY")
    print("=" * 60)
    print(f"Summary: {analysis.summary}")
    print(f"\nSpec Rules Found ({len(analysis.spec_rules)}):")
    for r in analysis.spec_rules:
        lines_str = ", ".join(map(str, r.source_lines)) if r.source_lines else "None"
        print(f"  [{r.id}] ({r.confidence}) {r.text} -> Lines: {lines_str}")

    print(f"\nRisk Areas ({len(analysis.risk_areas)}):")
    for risk in analysis.risk_areas:
        print(f"  - {risk}")

    print("\n" + "=" * 60)
    print(f"TEST SUITE SUMMARY ({len(tests)} Tests)")
    print("=" * 60)
    cat_counts = Counter(t.category for t in tests)
    print("Tests by Category:")
    for cat, count in sorted(cat_counts.items()):
        print(f"  - {cat:16s}: {count:2d} tests")

    print("\nGenerated Tests:")
    for t in tests:
        expect_str = ", ".join(e.serial_contains for e in t.expect)
        sensor_tag = " [DISCONNECTED]" if t.sensor == "disconnected" else ""
        print(
            f"  {t.id}: [{t.category.upper()}]{sensor_tag} {t.name} -> Expect: {expect_str}"
        )

    print("\n" + "=" * 60)
    print("SPECIFICATION RULE COVERAGE")
    print("=" * 60)
    cov = compute_coverage(tests)
    for r_id in ["R1", "R2", "R3", "R4", "R5", "R6"]:
        val = cov["rules"].get(r_id, [])
        if r_id == "R6":
            print(f"  [{r_id}]: {val}")
        elif val:
            print(f"  [{r_id}]: {', '.join(val)}")
        else:
            print(f"  [{r_id}]: (none)")


if __name__ == "__main__":
    main()
