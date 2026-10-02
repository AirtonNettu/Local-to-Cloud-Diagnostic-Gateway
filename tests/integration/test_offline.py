"""Offline / local-first integration tests (design B.18).

A fresh temporary data directory is used, the probe layer's network primitives
(``socket.create_connection``, ``socket.getaddrinfo`` and the ping subprocess)
are patched to simulate no connectivity, and the real CLI commands run. The
local diagnostics must succeed with the network classified OFFLINE (or UNKNOWN
in the second variant), the queued event must stay PENDING with its retry budget
untouched, and ``sync`` must abort cleanly without crashing.
"""

from __future__ import annotations

import errno
import socket
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent import commands
from agent.diagnostics import probes
from agent.storage import local_db

API_URL = "https://unreachable.invalid"
VALID_KEY = "k" * 40


@pytest.fixture
def offline_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[Path]:
    """Fresh data dir + cloud config so sync is enabled but unreachable."""
    db_path = tmp_path / "agent.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("DEMO_DATABASE_PATH", str(tmp_path / "demo.db"))
    monkeypatch.setenv("LOG_FILE", str(tmp_path / "logs" / "agent.log"))
    monkeypatch.setenv("API_BASE_URL", API_URL)
    monkeypatch.setenv("AGENT_API_KEY", VALID_KEY)
    monkeypatch.setenv("HTTP_TIMEOUT_SECONDS", "1")
    for key in ("DEVICE_ID", "DEVICE_NAME"):
        monkeypatch.delenv(key, raising=False)
    yield db_path


def _no_reply_ping(*_: object, **__: object) -> SimpleNamespace:
    """A ``subprocess.run`` stand-in returning a non-zero (no-reply) result."""
    return SimpleNamespace(returncode=1, stdout="Request timed out.", stderr="")


def _patch_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Internet TCP times out, DNS fails to resolve, ping gets no reply."""

    def _timeout(*_: object, **__: object) -> None:
        raise TimeoutError("simulated timeout")

    def _gaierror(*_: object, **__: object) -> None:
        raise socket.gaierror("simulated DNS failure")

    monkeypatch.setattr(socket, "create_connection", _timeout)
    monkeypatch.setattr(socket, "getaddrinfo", _gaierror)
    monkeypatch.setattr(probes.subprocess, "run", _no_reply_ping)


def _patch_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both connectivity checks ERROR (plain OSError), ping cannot execute."""

    def _eacces(*_: object, **__: object) -> None:
        raise OSError(errno.EACCES, "simulated")

    def _missing_ping(*_: object, **__: object) -> None:
        raise FileNotFoundError("ping not found")

    monkeypatch.setattr(socket, "create_connection", _eacces)
    monkeypatch.setattr(socket, "getaddrinfo", _eacces)
    monkeypatch.setattr(probes.subprocess, "run", _missing_ping)


def _ns(**kw: object) -> SimpleNamespace:
    base = {"json": False, "env_file": None, "log_level": None}
    base.update(kw)
    return SimpleNamespace(**base)


def test_offline_scan_queues_and_sync_aborts(
    offline_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_offline(monkeypatch)

    # Local diagnostics succeed and persist (exit 0 for a plain scan).
    assert commands.cmd_scan(_ns(sync=False)) == 0

    # The run enqueued one event and the network is OFFLINE.
    conn = local_db.connect(offline_env, read_only=True)
    try:
        pending = conn.execute(
            "SELECT COUNT(*) FROM sync_queue WHERE state = 'PENDING'"
        ).fetchone()[0]
        net_status = conn.execute(
            "SELECT network_status FROM diagnostic_runs ORDER BY started_at DESC"
        ).fetchone()[0]
        next_before = conn.execute(
            "SELECT next_attempt_at FROM sync_queue"
        ).fetchone()[0]
    finally:
        conn.close()
    assert pending == 1
    assert net_status == "OFFLINE"

    # Sync aborts offline (exit 3), nothing crashes.
    assert commands.cmd_sync(_ns(force=False)) == 3

    conn = local_db.connect(offline_env, read_only=True)
    try:
        state, count, next_after = conn.execute(
            "SELECT state, attempt_count, next_attempt_at FROM sync_queue"
        ).fetchone()
        offline_attempts = conn.execute(
            "SELECT error_code FROM sync_attempts WHERE outcome = 'OFFLINE'"
        ).fetchall()
    finally:
        conn.close()
    assert state == "PENDING"
    assert count == 0
    assert next_after == next_before  # next_attempt_at unchanged
    assert len(offline_attempts) == 1
    assert offline_attempts[0][0] == "REGISTRATION_OFFLINE"


def test_offline_other_commands_do_not_crash(
    offline_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_offline(monkeypatch)
    commands.cmd_scan(_ns(sync=False))
    # health / hardware / network are read-only and must succeed.
    assert commands.cmd_health(_ns()) == 0
    assert commands.cmd_hardware(_ns()) == 0
    assert commands.cmd_network(_ns()) == 0
    assert commands.cmd_status(_ns()) == 0


def test_unknown_variant_skips_connectivity_checks(
    offline_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_unknown(monkeypatch)
    assert commands.cmd_scan(_ns(sync=False)) == 0

    conn = local_db.connect(offline_env, read_only=True)
    try:
        net_status = conn.execute(
            "SELECT network_status FROM diagnostic_runs ORDER BY started_at DESC"
        ).fetchone()[0]
        gateway = conn.execute(
            """
            SELECT status FROM diagnostic_results
            WHERE result_type = 'check' AND name = 'network.gateway'
            """
        ).fetchone()
        internet = conn.execute(
            """
            SELECT status FROM diagnostic_results
            WHERE result_type = 'check' AND name = 'network.internet'
            """
        ).fetchone()
    finally:
        conn.close()
    assert net_status == "UNKNOWN"
    assert gateway[0] == "SKIPPED"
    assert internet[0] == "SKIPPED"
