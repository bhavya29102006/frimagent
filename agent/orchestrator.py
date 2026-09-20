"""Pipeline orchestrator: state machine managing the complete autonomous testing lifecycle."""

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from typing import Any, Callable

from agent.followup import generate_followup_tests
from agent.models import FirmwareAnalysis, RunManifest, TestCase, TestResult
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
    enable_followup: bool = False,
    max_followup_rounds: int = 1,
    simulator_name: str = "wokwi",
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
    if runner_fn is not None:
        run_func = runner_fn
    else:
        run_func = lambda test, firmware_dir, run_dir: run_test(
            test=test, firmware_dir=firmware_dir, run_dir=run_dir, simulator_name=simulator_name
        )
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

    # 6. Autonomous Follow-Up Loop (TASK-019)
    if enable_followup and not stopped and manifest.failed > 0:
        target_analysis = (
            dest_analysis if dest_analysis.is_file() else src_analysis
        )
        if target_analysis.is_file():
            try:
                analysis_model = FirmwareAnalysis.model_validate_json(
                    target_analysis.read_text(encoding="utf-8")
                )
                source_candidates = [
                    run_dir / "firmware_source.txt",
                    Path(firmware_dir) / "src" / "main.cpp",
                ]
                numbered_src = ""
                for cand in source_candidates:
                    if cand.is_file():
                        from agent.rootcause import number_source_code

                        numbered_src = number_source_code(
                            cand.read_text(encoding="utf-8")
                        )
                        break

                for round_idx in range(1, max_followup_rounds + 1):
                    if stop_event and stop_event.is_set():
                        stopped = True
                        break

                    failed_res = [
                        r for r in results if r.status in ("FAIL", "ERROR")
                    ]
                    followup_tests = generate_followup_tests(
                        failed_results=failed_res,
                        test_cases=tests,
                        analysis=analysis_model,
                        numbered_source=numbered_src or "No source code available",
                        round_num=round_idx,
                    )
                    if not followup_tests:
                        break

                    manifest.followup_rounds = round_idx
                    manifest.total_tests += len(followup_tests)
                    tests.extend(followup_tests)

                    # Update tests.json
                    tests_dump = [t.model_dump() for t in tests]
                    (run_dir / "tests.json").write_text(
                        json.dumps({"tests": tests_dump}, indent=2),
                        encoding="utf-8",
                    )

                    if callable(on_event):
                        try:
                            on_event(
                                {
                                    "type": "followup_started",
                                    "round": round_idx,
                                    "tests": [t.id for t in followup_tests],
                                    "count": len(followup_tests),
                                }
                            )
                        except Exception:
                            pass

                    for test in followup_tests:
                        if stop_event and stop_event.is_set():
                            stopped = True
                            break

                        if callable(on_event):
                            try:
                                on_event(
                                    {
                                        "type": "test_started",
                                        "test_id": test.id,
                                        "index": len(results) + 1,
                                        "total": manifest.total_tests,
                                    }
                                )
                            except Exception:
                                pass

                        try:
                            f_result = run_func(
                                test=test,
                                firmware_dir=firmware_dir,
                                run_dir=run_dir,
                            )
                        except Exception as exc:
                            f_result = TestResult(
                                test_id=test.id,
                                status="ERROR",
                                exit_code=-1,
                                duration_s=0.0,
                                expected=[
                                    e.serial_contains for e in test.expect
                                ],
                                observed_lines=[],
                                serial_log=f"Runner exception: {type(exc).__name__}: {exc}",
                                violated_must_not=[],
                                missing_expected=[
                                    e.serial_contains for e in test.expect
                                ],
                                error_message=f"{type(exc).__name__}: {exc}",
                            )

                        results.append(f_result)
                        if f_result.status == "PASS":
                            manifest.passed += 1
                        elif f_result.status == "FAIL":
                            manifest.failed += 1
                        else:
                            manifest.errors += 1

                        results_data = [r.model_dump() for r in results]
                        (run_dir / "results.json").write_text(
                            json.dumps(results_data, indent=2), encoding="utf-8"
                        )
                        (run_dir / "manifest.json").write_text(
                            manifest.model_dump_json(indent=2), encoding="utf-8"
                        )

                        if callable(on_event):
                            try:
                                on_event(
                                    {
                                        "type": "test_finished",
                                        "test_id": test.id,
                                        "result": f_result,
                                        "index": len(results),
                                        "total": manifest.total_tests,
                                    }
                                )
                            except Exception:
                                pass
            except Exception:
                pass

    # 7. Finalize RunManifest
    manifest.finished_at = datetime.now(timezone.utc).isoformat()
    manifest.status = "stopped" if stopped else "done"
    manifest.passed = sum(1 for r in results if r.status == "PASS")
    manifest.failed = sum(1 for r in results if r.status == "FAIL")
    manifest.errors = sum(1 for r in results if r.status == "ERROR")
    if not stopped:
        manifest.total_tests = len(results)
    else:
        manifest.total_tests = len(tests)

    (run_dir / "manifest.json").write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )

    # 8. Archive run into SQLite backend database
    try:
        from agent.db import save_run_record
        source_code_cand = Path(firmware_dir) / "src" / "main.cpp"
        src_text = source_code_cand.read_text(encoding="utf-8") if source_code_cand.is_file() else None
        save_run_record(
            manifest=manifest,
            results=results,
            findings=None,
            source_code=src_text,
            simulator_name=simulator_name,
        )
    except Exception:
        pass

    if callable(on_event):
        try:
            on_event({"type": "run_finished", "manifest": manifest})
        except Exception:
            pass

    return manifest
