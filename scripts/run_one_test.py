"""Script to run a single test case through Wokwi simulator (TASK-009).

Usage:
    python scripts/run_one_test.py <TEST_ID>
Example:
    python scripts/run_one_test.py T01
"""

from pathlib import Path
import json
import sys

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.models import TestCase, TestList
from agent.runner import run_test


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/run_one_test.py <TEST_ID>")
        sys.exit(1)

    target_id = sys.argv[1].strip()
    tests_file = PROJECT_ROOT / "runs" / "dev" / "tests.json"

    if not tests_file.is_file():
        print(f"Error: tests.json not found at {tests_file}")
        print("Please run 'python scripts/analyze_and_generate.py' first.")
        sys.exit(1)

    try:
        data = json.loads(tests_file.read_text(encoding="utf-8"))
        test_list = TestList.model_validate(data)
    except Exception as exc:
        print(f"Error parsing {tests_file}: {exc}")
        sys.exit(1)

    matching = [t for t in test_list.tests if t.id.upper() == target_id.upper()]
    if not matching:
        print(
            f"Error: Test '{target_id}' not found in {tests_file}. Available: {[t.id for t in test_list.tests]}"
        )
        sys.exit(1)

    test = matching[0]
    firmware_dir = PROJECT_ROOT / "firmware" / "fan_controller"
    run_dir = PROJECT_ROOT / "runs" / "dev"

    print(f"Running test {test.id}: {test.name} (category: {test.category})...")
    result = run_test(test=test, firmware_dir=firmware_dir, run_dir=run_dir)

    print("\n" + "=" * 60)
    print(f"TEST RESULT: {result.test_id}")
    print("=" * 60)
    status_icon = (
        "✅"
        if result.status == "PASS"
        else ("❌" if result.status == "FAIL" else "⚠")
    )
    print(
        f"Status:   {status_icon} {result.status} (exit code: {result.exit_code})"
    )
    print(f"Duration: {result.duration_s}s")
    print(f"Expected: {result.expected}")

    print("\nObserved Lines (last 8):")
    tail_lines = result.observed_lines[-8:] if result.observed_lines else []
    if tail_lines:
        for line in tail_lines:
            print(f"  {line}")
    else:
        print("  (no matching serial lines captured)")

    if result.error_message:
        print(f"\nError: {result.error_message}")


if __name__ == "__main__":
    main()
