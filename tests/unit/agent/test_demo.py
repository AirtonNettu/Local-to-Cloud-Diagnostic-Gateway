"""Demo mode tests (design B.12, review M1 + NIT4).

These assert the deterministic scenario outcomes, the hostile-environment
isolation (no subprocess/socket/psutil), the OFFLINE queue demonstration and the
demo-database safety guards (foreign/non-SQLite files are never deleted).
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pytest

from agent import commands, demo
from agent.storage import local_db
from agent.storage.local_db import DEMO_DB_APPLICATION_ID, LIVE_DB_APPLICATION_ID

# The expected scenario table (§B.12). Docs and behavior cannot drift from this.
_EXPECTED = {
    "HEALTHY": ("HEALTHY", "HEALTHY", ()),
    "DEGRADED_NETWORK": ("DEGRADED", "DEGRADED", ("HIGH_LATENCY", "PACKET_LOSS")),
    "LOW_DISK": ("CRITICAL", "HEALTHY", ("DISK_SPACE_CRITICAL",)),
    "HIGH_MEMORY": ("DEGRADED", "HEALTHY", ("MEMORY_PRESSURE",)),
    "DNS_FAILURE": ("DEGRADED", "DEGRADED", ("DNS_FAILURE",)),
    "OFFLINE_MODE": (
        "DEGRADED",
        "OFFLINE",
        ("INTERNET_CONNECTIVITY_FAILURE",),
    ),
}


def _args(scenario: str | None = None, *, all_: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        scenario=scenario, all=all_, json=False, env_file=None, log_level=None
    )


def _demo_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point DEMO/DATABASE paths at tmp and clear every overriding env var."""
    demo_path = tmp_path / "demo.db"
    live_path = tmp_path / "agent.db"
    for key in (
        "API_BASE_URL",
        "AGENT_API_KEY",
        "DEVICE_ID",
        "DEVICE_NAME",
        "SYNC_BATCH_SIZE",
        "RETRY_LIMIT",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DEMO_DATABASE_PATH", str(demo_path))
    monkeypatch.setenv("DATABASE_PATH", str(live_path))
    return demo_path


def test_scenario_table_matches_expected_outcomes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _demo_env(monkeypatch, tmp_path)
    settings = commands._load(_args())
    assert settings is not None
    runner = demo.DemoRunner(settings)
    assert runner.prepare_database() is None
    results = runner.run(list(demo.SCENARIOS))

    seen = {
        item.scenario.name: (
            item.result.status.value,
            item.result.network_status.value,
            tuple(a.rule_id for a in item.result.alerts),
        )
        for item in results
    }
    assert seen == _EXPECTED


def test_demo_all_hostile_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``demo --all`` never touches subprocess, sockets or psutil."""
    import socket
    import subprocess

    import psutil

    _demo_env(monkeypatch, tmp_path)

    def _boom(*_: object, **__: object) -> object:
        raise AssertionError("demo must not touch real resources")

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)
    monkeypatch.setattr(socket, "getaddrinfo", _boom)
    for name in (
        "cpu_percent",
        "cpu_count",
        "cpu_freq",
        "virtual_memory",
        "disk_partitions",
        "disk_usage",
        "boot_time",
        "net_if_addrs",
        "net_if_stats",
    ):
        monkeypatch.setattr(psutil, name, _boom, raising=False)

    code = commands.cmd_demo(_args(all_=True))
    assert code == 0
    out = capsys.readouterr().out
    for name in _EXPECTED:
        assert name in out


def test_demo_all_queue_pending_with_one_offline_attempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    demo_path = _demo_env(monkeypatch, tmp_path)
    assert commands.cmd_demo(_args(all_=True)) == 0

    conn = local_db.connect(demo_path, read_only=True)
    try:
        pending = conn.execute(
            "SELECT COUNT(*) FROM sync_queue WHERE state = 'PENDING'"
        ).fetchone()[0]
        attempts = conn.execute(
            "SELECT COUNT(*) FROM sync_attempts WHERE outcome = 'OFFLINE'"
        ).fetchone()[0]
        attempt_counts = [
            row[0]
            for row in conn.execute("SELECT attempt_count FROM sync_queue").fetchall()
        ]
    finally:
        conn.close()
    assert pending == 6  # all six demo events
    assert attempts == 6  # exactly one OFFLINE attempt each
    assert attempt_counts == [0, 0, 0, 0, 0, 0]  # released, budget untouched


def test_demo_scenario_offline_only_one_event(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    demo_path = _demo_env(monkeypatch, tmp_path)
    assert commands.cmd_demo(_args(scenario="OFFLINE_MODE")) == 0

    conn = local_db.connect(demo_path, read_only=True)
    try:
        pending = conn.execute(
            "SELECT COUNT(*) FROM sync_queue WHERE state = 'PENDING'"
        ).fetchone()[0]
        attempts = conn.execute(
            "SELECT COUNT(*) FROM sync_attempts WHERE outcome = 'OFFLINE'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert pending == 1
    assert attempts == 1


def test_demo_is_deterministic_across_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _demo_env(monkeypatch, tmp_path)
    settings = commands._load(_args())
    assert settings is not None

    def _signature() -> list[tuple[str, str, str, tuple[str, ...]]]:
        runner = demo.DemoRunner(settings)
        assert runner.prepare_database() is None
        return [
            (
                item.scenario.name,
                item.result.status.value,
                item.result.network_status.value,
                tuple(a.rule_id for a in item.result.alerts),
            )
            for item in runner.run(list(demo.SCENARIOS))
        ]

    assert _signature() == _signature()


def test_demo_removes_leftover_wal_and_shm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    demo_path = _demo_env(monkeypatch, tmp_path)
    # Create a real demo DB, then plant stale sidecars next to it.
    conn = local_db.connect(demo_path, demo=True)
    conn.close()
    wal = demo_path.with_name(demo_path.name + "-wal")
    shm = demo_path.with_name(demo_path.name + "-shm")
    wal.write_bytes(b"stale-wal")
    shm.write_bytes(b"stale-shm")

    runner = demo.DemoRunner(commands._load(_args()))  # type: ignore[arg-type]
    assert runner.prepare_database() is None
    # The old database and both sidecars are gone before any new connection.
    assert not wal.exists()
    assert not shm.exists()


def test_demo_leaves_foreign_sqlite_file_untouched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    demo_path = _demo_env(monkeypatch, tmp_path)
    # A live-marked SQLite file is "foreign": application_id differs.
    conn = sqlite3.connect(str(demo_path))
    conn.execute(f"PRAGMA application_id = {LIVE_DB_APPLICATION_ID}")
    conn.execute("CREATE TABLE keep (id INTEGER)")
    conn.execute("INSERT INTO keep VALUES (1)")
    conn.commit()
    conn.close()
    before = demo_path.read_bytes()

    code = commands.cmd_demo(_args(scenario="HEALTHY"))
    assert code == 2
    assert demo_path.read_bytes() == before  # untouched


def test_demo_leaves_non_sqlite_file_untouched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    demo_path = _demo_env(monkeypatch, tmp_path)
    demo_path.write_text("this is not a sqlite database", encoding="utf-8")

    code = commands.cmd_demo(_args(scenario="HEALTHY"))
    assert code == 2
    assert demo_path.read_text(encoding="utf-8") == "this is not a sqlite database"


def test_demo_refuses_same_file_as_live_db(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    shared = tmp_path / "shared.db"
    for key in ("API_BASE_URL", "AGENT_API_KEY", "DEVICE_ID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DEMO_DATABASE_PATH", str(shared))
    monkeypatch.setenv("DATABASE_PATH", str(shared))

    code = commands.cmd_demo(_args(scenario="HEALTHY"))
    assert code == 2


def test_demo_only_marks_demo_application_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    demo_path = _demo_env(monkeypatch, tmp_path)
    assert commands.cmd_demo(_args(all_=True)) == 0
    assert local_db.read_application_id(demo_path) == DEMO_DB_APPLICATION_ID
