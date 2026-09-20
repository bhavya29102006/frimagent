"""Unit tests for SQLite persistent backend database (agent/db.py)."""

from pathlib import Path
import pytest

from agent.db import (
    compute_firmware_hash,
    delete_firmware_cache,
    get_connection,
    get_db_stats,
    get_firmware_cache,
    get_run_record,
    list_db_runs,
    save_firmware_cache,
    save_run_record,
)
from agent.models import (
    Expectation,
    FirmwareAnalysis,
    RunManifest,
    TestCase,
    TestResult,
    TestStep,
)


def _make_dummy_analysis() -> FirmwareAnalysis:
    return FirmwareAnalysis(
        summary="Dummy Analysis",
        inputs=["pin 2"],
        outputs=["pin 13"],
        constants={"THRESHOLD": "30.0"},
        states=["IDLE", "RUNNING"],
        error_handling=["isnan check"],
        communication=["Serial 9600"],
        spec_rules=[],
        risk_areas=["hysteresis"],
    )


def _make_dummy_tests() -> list[TestCase]:
    return [
        TestCase(
            id="T01",
            name="Room Temp Test",
            category="normal",
            steps=[TestStep(set_temp=25.0, wait_ms=2500)],
            expect=[Expectation(serial_contains="fan=OFF")],
            rationale="Verify fan is off",
            round=0,
        )
    ]


def test_init_db_creates_tables(tmp_path):
    """Database schema creates firmware_cache and test_runs tables."""
    db_file = tmp_path / "test.db"
    conn = get_connection(db_file)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    assert "firmware_cache" in tables
    assert "test_runs" in tables
    conn.close()


def test_compute_firmware_hash():
    """Hash is deterministic and ignores trailing whitespace differences."""
    code1 = "void setup() {\n  pinMode(13, OUTPUT);\n}\n"
    code2 = "void setup() {  \n  pinMode(13, OUTPUT);  \n}\n\n"
    assert compute_firmware_hash(code1) == compute_firmware_hash(code2)


def test_save_and_get_firmware_cache(tmp_path):
    """Saving firmware cache allows instant retrieval by code hash."""
    db_file = tmp_path / "test.db"
    code = "void setup() { /* test */ }"
    analysis = _make_dummy_analysis()
    tests = _make_dummy_tests()

    # Initial cache miss
    miss = get_firmware_cache(code, db_path=db_file)
    assert miss is None

    # Save to cache
    fw_hash = save_firmware_cache(
        source_code=code,
        firmware_name="fan_controller",
        language="cpp",
        analysis=analysis,
        tests=tests,
        db_path=db_file,
    )
    assert len(fw_hash) == 64

    # Cache hit
    hit = get_firmware_cache(code, db_path=db_file)
    assert hit is not None
    assert hit["firmware_hash"] == fw_hash
    assert hit["firmware_name"] == "fan_controller"
    assert hit["language"] == "cpp"
    assert hit["analysis"].summary == "Dummy Analysis"
    assert len(hit["tests"]) == 1
    assert hit["tests"][0].id == "T01"


def test_delete_firmware_cache(tmp_path):
    """Deleting firmware cache removes the entry."""
    db_file = tmp_path / "test.db"
    code = "void loop() {}"
    save_firmware_cache(
        source_code=code,
        firmware_name="fan_controller",
        language="cpp",
        analysis=_make_dummy_analysis(),
        tests=_make_dummy_tests(),
        db_path=db_file,
    )

    deleted = delete_firmware_cache(code, db_path=db_file)
    assert deleted is True

    # Should now be a miss
    assert get_firmware_cache(code, db_path=db_file) is None


def test_save_and_get_run_record(tmp_path):
    """Run record is properly stored and retrievable."""
    db_file = tmp_path / "test.db"
    manifest = RunManifest(
        run_id="20260921-010000",
        firmware_name="fan_controller",
        started_at="2026-09-21T01:00:00Z",
        finished_at="2026-09-21T01:02:00Z",
        status="done",
        total_tests=16,
        passed=13,
        failed=3,
        errors=0,
        followup_rounds=0,
    )
    results = [
        TestResult(
            test_id="T01",
            status="PASS",
            duration_s=1.2,
            expected=["fan=OFF"],
            observed_lines=["[DATA] temp=25.0 fan=OFF"],
            serial_log="[DATA] temp=25.0 fan=OFF\n",
        )
    ]

    run_id = save_run_record(
        manifest=manifest,
        results=results,
        simulator_name="virtual_mock",
        db_path=db_file,
    )
    assert run_id == "20260921-010000"

    record = get_run_record(run_id, db_path=db_file)
    assert record is not None
    assert record["run_id"] == "20260921-010000"
    assert record["simulator_name"] == "virtual_mock"
    assert record["passed"] == 13
    assert record["failed"] == 3


def test_list_db_runs_and_stats(tmp_path):
    """Listing DB runs and stats reflects stored data."""
    db_file = tmp_path / "test.db"
    save_firmware_cache(
        source_code="void setup() {}",
        firmware_name="fw1",
        language="cpp",
        analysis=_make_dummy_analysis(),
        tests=_make_dummy_tests(),
        db_path=db_file,
    )
    manifest = RunManifest(
        run_id="run-1",
        firmware_name="fw1",
        started_at="2026-09-21T01:00:00Z",
        status="done",
        total_tests=1,
        passed=1,
        failed=0,
        errors=0,
    )
    save_run_record(manifest=manifest, results=[], simulator_name="wokwi", db_path=db_file)

    stats = get_db_stats(db_path=db_file)
    assert stats["cached_firmwares"] == 1
    assert stats["recorded_runs"] == 1

    runs = list_db_runs(limit=10, db_path=db_file)
    assert len(runs) == 1
    assert runs[0]["run_id"] == "run-1"
