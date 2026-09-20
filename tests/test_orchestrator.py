"""Unit tests for agent/orchestrator.py."""

import json
from pathlib import Path
import threading
import pytest

from agent.models import TestCase, TestResult
from agent.orchestrator import run_all


def _create_fixture_data(tmp_path: Path):
    source_dir = tmp_path / "source"
    source_dir.mkdir(parents=True, exist_ok=True)

    analysis = {
        "summary": "Fan controller firmware",
        "inputs": ["DHT22 pin 2"],
        "outputs": ["Fan pin 13"],
        "constants": {"ON_THRESHOLD": "30.0"},
        "states": ["IDLE", "RUNNING"],
        "error_handling": ["NaN check"],
        "communication": ["Serial 9600"],
        "spec_rules": [
            {"id": "R1", "text": "Turn fan on above 30", "source_lines": [10]}
        ],
        "risk_areas": ["Boundary operator"],
    }
    (source_dir / "analysis.json").write_text(
        json.dumps(analysis), encoding="utf-8"
    )

    tests = {
        "tests": [
            {
                "id": "T01",
                "name": "Normal Low",
                "category": "normal",
                "sensor": "normal",
                "steps": [{"set_temp": 25.0, "wait_ms": 2500}],
                "expect": [{"serial_contains": "temp=25.0 fan=OFF"}],
                "must_not": [],
                "rationale": "Verify fan OFF",
                "round": 0,
            },
            {
                "id": "T02",
                "name": "Boundary Threshold",
                "category": "boundary",
                "sensor": "normal",
                "steps": [{"set_temp": 30.0, "wait_ms": 2500}],
                "expect": [{"serial_contains": "temp=30.0 fan=ON"}],
                "must_not": [],
                "rationale": "Verify fan ON",
                "round": 0,
            },
            {
                "id": "T03",
                "name": "Extreme Temp",
                "category": "abnormal",
                "sensor": "normal",
                "steps": [{"set_temp": 80.0, "wait_ms": 2500}],
                "expect": [{"serial_contains": "temp=80.0 fan=ON"}],
                "must_not": [],
                "rationale": "Verify abnormal value",
                "round": 0,
            },
        ]
    }
    (source_dir / "tests.json").write_text(json.dumps(tests), encoding="utf-8")
    return source_dir


def test_run_all_full_cycle(tmp_path: Path):
    source_dir = _create_fixture_data(tmp_path)
    runs_dir = tmp_path / "runs"

    def mock_runner(test: TestCase, firmware_dir, run_dir) -> TestResult:
        if test.id == "T01":
            return TestResult(
                test_id=test.id,
                status="PASS",
                exit_code=0,
                duration_s=12.0,
                expected=["temp=25.0 fan=OFF"],
                observed_lines=["temp=25.0 fan=OFF"],
                serial_log="PASS log",
            )
        elif test.id == "T02":
            return TestResult(
                test_id=test.id,
                status="FAIL",
                exit_code=42,
                duration_s=25.0,
                expected=["temp=30.0 fan=ON"],
                observed_lines=["temp=30.0 fan=OFF"],
                serial_log="FAIL log",
            )
        else:
            return TestResult(
                test_id=test.id,
                status="ERROR",
                exit_code=1,
                duration_s=1.0,
                expected=["temp=80.0 fan=ON"],
                observed_lines=[],
                serial_log="ERROR log",
                error_message="Simulation crash",
            )

    events = []

    def on_event(ev):
        events.append(ev)

    manifest = run_all(
        run_id="run_cycle",
        source_dir=source_dir,
        firmware_dir="firmware/fan_controller",
        on_event=on_event,
        runner_fn=mock_runner,
        runs_base_dir=runs_dir,
    )

    assert manifest.total_tests == 3
    assert manifest.passed == 1
    assert manifest.failed == 1
    assert manifest.errors == 1
    assert manifest.status == "done"
    assert manifest.finished_at is not None

    out_dir = runs_dir / manifest.run_id
    assert (out_dir / "analysis.json").is_file()
    assert (out_dir / "tests.json").is_file()
    assert (out_dir / "manifest.json").is_file()
    assert (out_dir / "results.json").is_file()

    results_data = json.loads(
        (out_dir / "results.json").read_text(encoding="utf-8")
    )
    assert len(results_data) == 3
    assert [r["status"] for r in results_data] == ["PASS", "FAIL", "ERROR"]

    # Verify event callbacks
    types = [e["type"] for e in events]
    assert types == [
        "test_started",
        "test_finished",
        "test_started",
        "test_finished",
        "test_started",
        "test_finished",
        "run_finished",
    ]


def test_run_all_only_ids_filter(tmp_path: Path):
    source_dir = _create_fixture_data(tmp_path)
    runs_dir = tmp_path / "runs"

    executed = []

    def mock_runner(test: TestCase, firmware_dir, run_dir) -> TestResult:
        executed.append(test.id)
        return TestResult(
            test_id=test.id,
            status="PASS",
            exit_code=0,
            duration_s=5.0,
            expected=[],
            observed_lines=[],
            serial_log="",
        )

    manifest = run_all(
        run_id="run_only",
        source_dir=source_dir,
        only_ids="T01,T03",
        runner_fn=mock_runner,
        runs_base_dir=runs_dir,
    )

    assert executed == ["T01", "T03"]
    assert manifest.total_tests == 2
    assert manifest.passed == 2
    assert manifest.status == "done"


def test_run_all_stop_event(tmp_path: Path):
    source_dir = _create_fixture_data(tmp_path)
    runs_dir = tmp_path / "runs"
    stop_signal = threading.Event()

    executed = []

    def mock_runner(test: TestCase, firmware_dir, run_dir) -> TestResult:
        executed.append(test.id)
        # Signal stop after first test completes
        stop_signal.set()
        return TestResult(
            test_id=test.id,
            status="PASS",
            exit_code=0,
            duration_s=5.0,
            expected=[],
            observed_lines=[],
            serial_log="",
        )

    manifest = run_all(
        run_id="run_stop",
        source_dir=source_dir,
        stop_event=stop_signal,
        runner_fn=mock_runner,
        runs_base_dir=runs_dir,
    )

    assert executed == ["T01"]
    assert manifest.status == "stopped"
    assert manifest.total_tests == 3
    assert manifest.passed == 1
    assert manifest.failed == 0


def test_run_all_runner_exception_never_aborts_run(tmp_path: Path):
    source_dir = _create_fixture_data(tmp_path)
    runs_dir = tmp_path / "runs"

    def crashing_runner(test: TestCase, firmware_dir, run_dir) -> TestResult:
        if test.id == "T01":
            raise RuntimeError("Unexpected runner crash")
        return TestResult(
            test_id=test.id,
            status="PASS",
            exit_code=0,
            duration_s=2.0,
            expected=[],
            observed_lines=[],
            serial_log="",
        )

    manifest = run_all(
        run_id="run_crash",
        source_dir=source_dir,
        runner_fn=crashing_runner,
        runs_base_dir=runs_dir,
    )

    assert manifest.total_tests == 3
    assert manifest.errors == 1
    assert manifest.passed == 2
    assert manifest.status == "done"

    out_dir = runs_dir / manifest.run_id
    results_data = json.loads(
        (out_dir / "results.json").read_text(encoding="utf-8")
    )
    assert len(results_data) == 3
    assert results_data[0]["status"] == "ERROR"
    assert "Unexpected runner crash" in results_data[0]["error_message"]


def test_run_all_with_followup(tmp_path: Path):
    source_dir = _create_fixture_data(tmp_path)
    runs_dir = tmp_path / "runs"

    executed = []

    def mock_runner(test: TestCase, firmware_dir, run_dir) -> TestResult:
        executed.append(test.id)
        # T02 fails (triggers follow-up)
        status = "FAIL" if test.id == "T02" else "PASS"
        exit_code = 42 if test.id == "T02" else 0
        return TestResult(
            test_id=test.id,
            status=status,
            exit_code=exit_code,
            duration_s=2.0,
            expected=["dummy"],
            observed_lines=["dummy"],
            serial_log="",
        )

    manifest = run_all(
        run_id="run_followup",
        source_dir=source_dir,
        enable_followup=True,
        runner_fn=mock_runner,
        runs_base_dir=runs_dir,
    )

    assert manifest.followup_rounds == 1
    assert manifest.total_tests > 3
    assert any(tid.startswith("F") for tid in executed)

