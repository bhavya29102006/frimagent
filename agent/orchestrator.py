"""Pipeline orchestrator: state machine managing the complete autonomous testing lifecycle."""

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from typing import Any, Callable

from agent.models import RunManifest, TestCase, TestResult
from agent.runner import run_test


def run_all(
    run_id: str | None = None,
    source_dir: Path | str = "runs/dev",
    firmware_dir: Path | str = "firmware/fan_controller",
    on_event: Callable[[dict[str, Any]], None] | None = None,
    stop_event: Any = None,
    only_ids: list[str] | str | None = None,
    runner_fn: Callable[..., TestResult] | None = None,
    runs_base_dir: Path | str = "runs",
) -> RunManifest:
    """Execute all tests sequentially with progress tracking and persistent state.

    - Reuses existing analysis.json and tests.json from source_dir (no Gemini calls).
    - If run_id is None, generates timestamp YYYYMMDD-HHMMSS.
    - Saves results.json and updates manifest.json after EVERY test.
    - Emits on_event callbacks for test_started, test_finished, run_finished.
    - Supports early termination via stop_event.
    - Single test failures or errors never stop the overall run.
    """
    if run_id is None:
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")

    run_dir = Path(runs_base_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    src = Path(source_dir).resolve()
    run_dir_resolved = run_dir.resolve()

    # 1. Copy analysis.json and tests.json into runs/<run_id>/
    src_analysis = src / "analysis.json"
    dest_analysis = run_dir / "analysis.json"
    if src_analysis.is_file() and src_analysis.resolve() != dest_analysis.resolve():
        shutil.copy2(src_analysis, dest_analysis)

    src_tests = src / "tests.json"
    dest_tests = run_dir / "tests.json"
    if src_tests.is_file() and src_tests.resolve() != dest_tests.resolve():
        shutil.copy2(src_tests, dest_tests)

    # 2. Load test cases
    target_tests_file = dest_tests if dest_tests.is_file() else src_tests
    if not target_tests_file.is_file():
        raise FileNotFoundError(
            f"tests.json not found in {source_dir} or {run_dir}"
        )

    raw_tests_data = json.loads(target_tests_file.read_text(encoding="utf-8"))
    if isinstance(raw_tests_data, dict) and "tests" in raw_tests_data:
        all_tests = [
            TestCase.model_validate(t) for t in raw_tests_data["tests"]
        ]
    elif isinstance(raw_tests_data, list):
        all_tests = [TestCase.model_validate(t) for t in raw_tests_data]
    else:
        raise ValueError(f"Unrecognized tests format in {target_tests_file}")

    # 3. Filter only_ids if provided
    if only_ids:
        if isinstance(only_ids, str):
            target_ids = {s.strip() for s in only_ids.split(",") if s.strip()}
        else:
            target_ids = set(only_ids)
        tests = [t for t in all_tests if t.id in target_ids]
    else:
        tests = all_tests

    # 4. Initialize RunManifest
    fw_path = Path(firmware_dir)
    firmware_name = fw_path.name or "fan_controller"

    manifest = RunManifest(
        run_id=run_id,
        firmware_name=firmware_name,
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at=None,
        status="running",
        total_tests=len(tests),
        passed=0,
        failed=0,
        errors=0,
        followup_rounds=0,
    )

    (run_dir / "manifest.json").write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )
    (run_dir / "results.json").write_text("[]", encoding="utf-8")

    # 5. Run loop
    run_func = runner_fn if runner_fn is not None else run_test
    results: list[TestResult] = []
    stopped = False
    total = len(tests)

    for i, test in enumerate(tests, start=1):
        # Check stop flag before starting the next test
        if stop_event and stop_event.is_set():
            stopped = True
            break

        if callable(on_event):
            try:
                on_event(
                    {
                        "type": "test_started",
                        "test_id": test.id,
                        "index": i,
                        "total": total,
                    }
                )
            except Exception:
                pass

        result: TestResult
        try:
            result = run_func(
                test=test, firmware_dir=firmware_dir, run_dir=run_dir
            )
        except Exception as exc:
            result = TestResult(
                test_id=test.id,
                status="ERROR",
                exit_code=-1,
                duration_s=0.0,
                expected=[e.serial_contains for e in test.expect],
                observed_lines=[],
                serial_log=f"Runner exception: {type(exc).__name__}: {exc}",
                violated_must_not=[],
                missing_expected=[e.serial_contains for e in test.expect],
                error_message=f"{type(exc).__name__}: {exc}",
            )

        results.append(result)

        if result.status == "PASS":
            manifest.passed += 1
        elif result.status == "FAIL":
            manifest.failed += 1
        else:
            manifest.errors += 1

        # Write results.json after EVERY test
        results_data = [r.model_dump() for r in results]
        (run_dir / "results.json").write_text(
            json.dumps(results_data, indent=2), encoding="utf-8"
        )

        # Update manifest.json after EVERY test with current counts
        (run_dir / "manifest.json").write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )

        if callable(on_event):
            try:
                on_event(
                    {
                        "type": "test_finished",
                        "test_id": test.id,
                        "result": result,
                        "index": i,
                        "total": total,
                    }
                )
            except Exception:
                pass

        # Check stop flag after finishing the test
        if stop_event and stop_event.is_set():
            stopped = True
            break

    # 6. Finalize RunManifest
    manifest.finished_at = datetime.now(timezone.utc).isoformat()
    manifest.status = "stopped" if stopped else "done"

    (run_dir / "manifest.json").write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )

    if callable(on_event):
        try:
            on_event({"type": "run_finished", "manifest": manifest})
        except Exception:
            pass

    return manifest
