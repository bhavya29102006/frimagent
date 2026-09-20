"""Persistent SQLite backend database for FirmAgent (runs/firmagent.db).

Stores:
1. Firmware Cache (firmware_cache table):
   - SHA-256 fingerprint hash of firmware source code.
   - Cached FirmwareAnalysis and TestList JSON so re-testing the same firmware
     loads instantly from database without re-invoking Gemini (zero token cost, zero latency).
2. Test Run History (test_runs table):
   - Manifest metrics, results, findings, and logs archived persistently.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Optional

from agent.models import Finding, FirmwareAnalysis, RunManifest, TestCase, TestList, TestResult

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "runs" / "firmagent.db"


def get_db_path(db_path: Optional[Path | str] = None) -> Path:
    """Resolve database path, defaulting to runs/firmagent.db."""
    if db_path is not None:
        p = Path(db_path).resolve()
    else:
        p = DEFAULT_DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def get_connection(db_path: Optional[Path | str] = None) -> sqlite3.Connection:
    """Create a sqlite3 connection and initialize schema if not present."""
    p = get_db_path(db_path)
    conn = sqlite3.connect(str(p), timeout=10.0)
    conn.row_factory = sqlite3.Row
    init_db_schema(conn)
    return conn


def init_db_schema(conn: sqlite3.Connection) -> None:
    """Initialize SQLite tables and indexes."""
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS firmware_cache (
            firmware_hash TEXT PRIMARY KEY,
            firmware_name TEXT NOT NULL,
            language TEXT NOT NULL,
            source_code TEXT NOT NULL,
            analysis_json TEXT NOT NULL,
            tests_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS test_runs (
            run_id TEXT PRIMARY KEY,
            firmware_hash TEXT,
            firmware_name TEXT NOT NULL,
            simulator_name TEXT NOT NULL,
            status TEXT NOT NULL,
            total_tests INTEGER NOT NULL,
            passed INTEGER NOT NULL,
            failed INTEGER NOT NULL,
            errors INTEGER NOT NULL,
            manifest_json TEXT NOT NULL,
            results_json TEXT NOT NULL,
            findings_json TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_firmware_cache_hash ON firmware_cache(firmware_hash)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_test_runs_started ON test_runs(started_at)"
    )
    conn.commit()


def compute_firmware_hash(source_code: str) -> str:
    """Compute normalized SHA-256 fingerprint hash of firmware source code."""
    normalized = "\n".join(line.rstrip() for line in source_code.strip().splitlines())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def get_firmware_cache(
    source_code: str,
    db_path: Optional[Path | str] = None,
) -> Optional[dict[str, Any]]:
    """Retrieve cached analysis and tests by firmware source code hash.

    Returns dict with keys:
        'firmware_hash', 'firmware_name', 'language', 'analysis', 'tests', 'created_at'
    or None if cache miss.
    """
    fw_hash = compute_firmware_hash(source_code)
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM firmware_cache WHERE firmware_hash = ?",
            (fw_hash,),
        )
        row = cursor.fetchone()
        if row is None:
            return None

        analysis_data = json.loads(row["analysis_json"])
        tests_data = json.loads(row["tests_json"])
        raw_tests = tests_data.get("tests", []) if isinstance(tests_data, dict) else tests_data

        return {
            "firmware_hash": row["firmware_hash"],
            "firmware_name": row["firmware_name"],
            "language": row["language"],
            "source_code": row["source_code"],
            "analysis": FirmwareAnalysis.model_validate(analysis_data),
            "tests": [TestCase.model_validate(t) for t in raw_tests],
            "created_at": row["created_at"],
        }
    finally:
        conn.close()


def get_firmware_cache_by_name(
    firmware_name: str,
    db_path: Optional[Path | str] = None,
) -> Optional[dict[str, Any]]:
    """Retrieve the most recent cached analysis and tests by firmware name.

    Ensures that when a firmware is patched or tested, the exact same test suite
    persists in SQLite rather than regenerating a new test suite on every code edit.
    """
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM firmware_cache WHERE firmware_name = ? ORDER BY created_at DESC LIMIT 1",
            (firmware_name,),
        )
        row = cursor.fetchone()
        if row is None:
            return None

        analysis_data = json.loads(row["analysis_json"])
        tests_data = json.loads(row["tests_json"])
        raw_tests = tests_data.get("tests", []) if isinstance(tests_data, dict) else tests_data

        return {
            "firmware_hash": row["firmware_hash"],
            "firmware_name": row["firmware_name"],
            "language": row["language"],
            "source_code": row["source_code"],
            "analysis": FirmwareAnalysis.model_validate(analysis_data),
            "tests": [TestCase.model_validate(t) for t in raw_tests],
            "created_at": row["created_at"],
        }
    finally:
        conn.close()


def save_firmware_cache(
    source_code: str,
    firmware_name: str,
    language: str,
    analysis: FirmwareAnalysis | dict[str, Any],
    tests: list[TestCase] | dict[str, Any],
    db_path: Optional[Path | str] = None,
) -> str:
    """Store or update analysis and tests in firmware_cache table.

    Returns firmware_hash.
    """
    fw_hash = compute_firmware_hash(source_code)
    analysis_json = (
        analysis.model_dump_json(indent=2)
        if hasattr(analysis, "model_dump_json")
        else json.dumps(analysis, indent=2)
    )

    if isinstance(tests, list):
        tests_payload = {"tests": [t.model_dump() if hasattr(t, "model_dump") else t for t in tests]}
    elif hasattr(tests, "model_dump"):
        tests_payload = tests.model_dump()
    else:
        tests_payload = tests

    tests_json = json.dumps(tests_payload, indent=2)
    now_iso = datetime.now(timezone.utc).isoformat()

    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO firmware_cache (firmware_hash, firmware_name, language, source_code, analysis_json, tests_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(firmware_hash) DO UPDATE SET
                firmware_name = excluded.firmware_name,
                language = excluded.language,
                source_code = excluded.source_code,
                analysis_json = excluded.analysis_json,
                tests_json = excluded.tests_json,
                created_at = excluded.created_at
            """,
            (fw_hash, firmware_name, language, source_code, analysis_json, tests_json, now_iso),
        )
        conn.commit()
        return fw_hash
    finally:
        conn.close()


def delete_firmware_cache(
    source_code: str,
    db_path: Optional[Path | str] = None,
) -> bool:
    """Remove a firmware entry from the cache."""
    fw_hash = compute_firmware_hash(source_code)
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM firmware_cache WHERE firmware_hash = ?",
            (fw_hash,),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def save_run_record(
    manifest: RunManifest | dict[str, Any],
    results: list[TestResult] | list[dict[str, Any]],
    findings: Optional[list[Finding] | list[dict[str, Any]]] = None,
    source_code: Optional[str] = None,
    simulator_name: str = "wokwi",
    db_path: Optional[Path | str] = None,
) -> str:
    """Save a completed test run to test_runs table.

    Returns run_id.
    """
    m_dict = manifest.model_dump() if hasattr(manifest, "model_dump") else manifest
    run_id = m_dict.get("run_id", "")
    firmware_name = m_dict.get("firmware_name", "unknown")
    status = m_dict.get("status", "done")
    total_tests = m_dict.get("total_tests", len(results))
    passed = m_dict.get("passed", sum(1 for r in results if (r.status if hasattr(r, 'status') else r.get('status')) == "PASS"))
    failed = m_dict.get("failed", sum(1 for r in results if (r.status if hasattr(r, 'status') else r.get('status')) == "FAIL"))
    errors = m_dict.get("errors", sum(1 for r in results if (r.status if hasattr(r, 'status') else r.get('status')) == "ERROR"))
    started_at = m_dict.get("started_at", datetime.now(timezone.utc).isoformat())
    finished_at = m_dict.get("finished_at")

    fw_hash = compute_firmware_hash(source_code) if source_code else None

    manifest_json = json.dumps(m_dict, indent=2)
    results_json = json.dumps(
        [r.model_dump() if hasattr(r, "model_dump") else r for r in results],
        indent=2,
    )
    findings_json = (
        json.dumps(
            [f.model_dump() if hasattr(f, "model_dump") else f for f in findings],
            indent=2,
        )
        if findings is not None
        else "[]"
    )
    now_iso = datetime.now(timezone.utc).isoformat()

    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO test_runs (
                run_id, firmware_hash, firmware_name, simulator_name, status,
                total_tests, passed, failed, errors, manifest_json,
                results_json, findings_json, started_at, finished_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                status = excluded.status,
                total_tests = excluded.total_tests,
                passed = excluded.passed,
                failed = excluded.failed,
                errors = excluded.errors,
                manifest_json = excluded.manifest_json,
                results_json = excluded.results_json,
                findings_json = excluded.findings_json,
                finished_at = excluded.finished_at
            """,
            (
                run_id, fw_hash, firmware_name, simulator_name, status,
                total_tests, passed, failed, errors, manifest_json,
                results_json, findings_json, started_at, finished_at, now_iso,
            ),
        )
        conn.commit()
        return run_id
    finally:
        conn.close()


def get_run_record(
    run_id: str,
    db_path: Optional[Path | str] = None,
) -> Optional[dict[str, Any]]:
    """Retrieve run record from database."""
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM test_runs WHERE run_id = ?", (run_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(row)
    finally:
        conn.close()


def list_db_runs(
    limit: int = 50,
    db_path: Optional[Path | str] = None,
) -> list[dict[str, Any]]:
    """List recent runs stored in the database."""
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT run_id, firmware_name, simulator_name, status,
                   total_tests, passed, failed, errors, started_at, finished_at
            FROM test_runs
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_db_stats(db_path: Optional[Path | str] = None) -> dict[str, int]:
    """Return count of cached firmwares and runs stored in DB."""
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM firmware_cache")
        cached_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM test_runs")
        runs_count = cursor.fetchone()[0]
        return {"cached_firmwares": cached_count, "recorded_runs": runs_count}
    finally:
        conn.close()
