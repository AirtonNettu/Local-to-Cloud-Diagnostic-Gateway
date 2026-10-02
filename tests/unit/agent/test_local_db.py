"""Tests for the local SQLite database layer (design B.8, review M1/NIT12)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from agent.storage import local_db
from agent.storage.local_db import (
    DEMO_DB_APPLICATION_ID,
    LIVE_DB_APPLICATION_ID,
    SCHEMA_VERSION,
    LocalStore,
    SchemaOutdatedError,
    StorageError,
)
from shared.models.diagnostic import (
    Alert,
    Check,
    CheckStatus,
    DiagnosticResult,
    HealthStatus,
    Metric,
    NetworkStatus,
    RunSource,
    Severity,
)


def _result(device_id: str = "demo-device-0001") -> DiagnosticResult:
    return DiagnosticResult(
        run_id="018f4e2b-0000-7000-8000-000000000001",
        device_id=device_id,
        started_at="2024-01-02T03:04:05.678Z",
        finished_at="2024-01-02T03:04:06.000Z",
        source=RunSource.LIVE,
        status=HealthStatus.HEALTHY,
        network_status=NetworkStatus.HEALTHY,
        checks=(
            Check("cpu.usage", CheckStatus.PASS, "ok", ("avg 10%",), "t"),
        ),
        alerts=(
            Alert("HIGH_CPU_USAGE", Severity.WARNING, "high", None, "cool it"),
        ),
        metrics=(Metric("cpu.usage_percent", 10.0, "percent"),),
        facts={"cpu": {"model": "x"}},
    )


def test_writable_creates_five_tables_and_version(tmp_path: Path) -> None:
    conn = local_db.connect(tmp_path / "sub" / "agent.db")
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {
            "devices",
            "diagnostic_runs",
            "diagnostic_results",
            "sync_queue",
            "sync_attempts",
        } <= tables
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == SCHEMA_VERSION
    finally:
        conn.close()


def test_partial_unique_index_exists(tmp_path: Path) -> None:
    conn = local_db.connect(tmp_path / "agent.db")
    try:
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert "idx_devices_single_local" in indexes
    finally:
        conn.close()


def test_live_and_demo_application_id(tmp_path: Path) -> None:
    live = local_db.connect(tmp_path / "live.db")
    demo = local_db.connect(tmp_path / "demo.db", demo=True)
    try:
        live_id = live.execute("PRAGMA application_id").fetchone()[0]
        demo_id = demo.execute("PRAGMA application_id").fetchone()[0]
        assert live_id == LIVE_DB_APPLICATION_ID
        assert demo_id == DEMO_DB_APPLICATION_ID
    finally:
        live.close()
        demo.close()


def test_read_application_id_helper(tmp_path: Path) -> None:
    path = tmp_path / "demo.db"
    conn = local_db.connect(path, demo=True)
    conn.close()
    assert local_db.read_application_id(path) == DEMO_DB_APPLICATION_ID
    assert local_db.read_application_id(tmp_path / "missing.db") is None


def test_read_only_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(StorageError):
        local_db.connect(tmp_path / "missing.db", read_only=True)


def test_read_only_no_migration_and_reads_wal(tmp_path: Path) -> None:
    path = tmp_path / "agent.db"
    writer = local_db.connect(path)
    assert writer.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    writer.execute(
        "INSERT INTO devices (device_id, device_name, hostname, is_local, "
        "created_at) VALUES ('d1', 'n', 'h', 1, 't')"
    )
    writer.commit()
    writer.close()

    reader = local_db.connect(path, read_only=True)
    try:
        # No PRAGMA change, no migration: user_version stays current.
        assert reader.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        rows = reader.execute("SELECT device_id FROM devices").fetchall()
        assert rows == [("d1",)]
        # A read-only connection cannot write.
        with pytest.raises(sqlite3.OperationalError):
            reader.execute(
                "INSERT INTO devices (device_id, device_name, hostname, "
                "is_local, created_at) VALUES ('d2', 'n', 'h', 0, 't')"
            )
    finally:
        reader.close()


def test_read_only_outdated_user_version(tmp_path: Path) -> None:
    path = tmp_path / "agent.db"
    conn = local_db.connect(path)
    conn.execute("PRAGMA user_version = 0")
    conn.commit()
    conn.close()
    with pytest.raises(SchemaOutdatedError):
        local_db.connect(path, read_only=True)


def test_save_run_writes_run_results_and_queue(tmp_path: Path) -> None:
    path = tmp_path / "agent.db"
    conn = local_db.connect(path)
    try:
        conn.execute(
            "INSERT INTO devices (device_id, device_name, hostname, is_local, "
            "created_at) VALUES ('demo-device-0001', 'n', 'h', 1, 't')"
        )
        conn.commit()
        store = LocalStore(conn)
        store.save_run(_result(), enqueue_event=True)

        assert conn.execute("SELECT COUNT(*) FROM diagnostic_runs").fetchone()[0] == 1
        # 1 check + 1 alert + 1 metric
        assert conn.execute(
            "SELECT COUNT(*) FROM diagnostic_results"
        ).fetchone()[0] == 3
        queue = conn.execute(
            "SELECT device_id, state, attempt_count FROM sync_queue"
        ).fetchone()
        assert queue == ("demo-device-0001", "PENDING", 0)
    finally:
        conn.close()


def test_save_run_without_enqueue_leaves_queue_empty(tmp_path: Path) -> None:
    path = tmp_path / "agent.db"
    conn = local_db.connect(path)
    try:
        conn.execute(
            "INSERT INTO devices (device_id, device_name, hostname, is_local, "
            "created_at) VALUES ('demo-device-0001', 'n', 'h', 1, 't')"
        )
        conn.commit()
        LocalStore(conn).save_run(_result(), enqueue_event=False)
        assert conn.execute("SELECT COUNT(*) FROM sync_queue").fetchone()[0] == 0
    finally:
        conn.close()


def test_save_run_requires_device_id(tmp_path: Path) -> None:
    conn = local_db.connect(tmp_path / "agent.db")
    try:
        result = DiagnosticResult(
            run_id="r",
            device_id=None,
            started_at="t",
            finished_at="t",
            source=RunSource.LIVE,
            status=HealthStatus.UNKNOWN,
            network_status=NetworkStatus.UNKNOWN,
            checks=(),
            alerts=(),
            metrics=(),
            facts={},
        )
        with pytest.raises(StorageError):
            LocalStore(conn).save_run(result, enqueue_event=False)
    finally:
        conn.close()


def test_save_run_transaction_rolls_back_on_foreign_key_violation(
    tmp_path: Path,
) -> None:
    # No matching device row -> foreign key violation -> StorageError, nothing
    # persisted (the whole transaction rolls back).
    conn = local_db.connect(tmp_path / "agent.db")
    try:
        with pytest.raises(StorageError):
            LocalStore(conn).save_run(_result(), enqueue_event=True)
        assert conn.execute("SELECT COUNT(*) FROM diagnostic_runs").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM diagnostic_results").fetchone()[
            0
        ] == 0
        assert conn.execute("SELECT COUNT(*) FROM sync_queue").fetchone()[0] == 0
    finally:
        conn.close()
