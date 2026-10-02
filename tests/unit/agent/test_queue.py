"""Sync-queue state-machine tests (design B.9)."""

from __future__ import annotations

import random
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent.storage import local_db
from agent.storage.local_db import LocalStore
from agent.storage.queue import (
    SYNC_LEASE_SECONDS,
    InvalidTransitionError,
    SyncQueue,
)
from agent.sync.retry import BackoffPolicy
from shared.models.diagnostic import (
    DiagnosticResult,
    HealthStatus,
    NetworkStatus,
    RunSource,
)
from shared.utils.ids import new_uuid7
from shared.utils.timeutil import to_iso

DEVICE = "demo-device-0001"
OTHER = "other-device-0002"

# Enqueue stamps ``next_attempt_at`` with the real clock, so the test clock must
# be at or after it for events to be due. ``_now()`` is computed fresh on each
# call (always slightly ahead of the real clock) so a slow earlier test in the
# session cannot leave a stale, now-in-the-past moment that makes events "not
# due" and breaks claiming.
def _now() -> datetime:
    return datetime.now(UTC) + timedelta(seconds=5)


def _result(device_id: str) -> DiagnosticResult:
    now = to_iso(_now())
    return DiagnosticResult(
        run_id=new_uuid7(),
        device_id=device_id,
        started_at=now,
        finished_at=now,
        source=RunSource.LIVE,
        status=HealthStatus.HEALTHY,
        network_status=NetworkStatus.HEALTHY,
        checks=(),
        alerts=(),
        metrics=(),
        facts={},
    )


def _insert_device(conn: sqlite3.Connection, device_id: str, is_local: int) -> None:
    conn.execute(
        """
        INSERT INTO devices (device_id, device_name, hostname, is_local, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (device_id, device_id, "host", is_local, to_iso(_now())),
    )
    conn.commit()


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = local_db.connect(tmp_path / "agent.db")
    _insert_device(connection, DEVICE, 1)
    _insert_device(connection, OTHER, 0)
    yield connection
    connection.close()


def _enqueue(conn: sqlite3.Connection, device_id: str = DEVICE) -> str:
    result = _result(device_id)
    LocalStore(conn).save_run(result, enqueue_event=True)
    row = conn.execute(
        "SELECT event_id FROM sync_queue WHERE run_id = ?", (result.run_id,)
    ).fetchone()
    return str(row[0])


def _policy() -> BackoffPolicy:
    return BackoffPolicy(base_s=60, max_s=3600, rng=random.Random(1))


def _state(conn: sqlite3.Connection, event_id: str) -> str:
    return str(
        conn.execute(
            "SELECT state FROM sync_queue WHERE event_id = ?", (event_id,)
        ).fetchone()[0]
    )


def test_claim_filters_by_device(conn: sqlite3.Connection) -> None:
    mine = _enqueue(conn, DEVICE)
    _enqueue(conn, OTHER)
    queue = SyncQueue(conn)
    claimed = queue.claim_due(DEVICE, 10, _now())
    assert [e.event_id for e in claimed] == [mine]
    assert queue.other_device_pending(DEVICE) == 1


def test_mark_synced_terminal(conn: sqlite3.Connection) -> None:
    event_id = _enqueue(conn)
    queue = SyncQueue(conn)
    claimed = queue.claim_due(DEVICE, 10, _now())
    queue.mark_synced([event_id], "ACCEPTED", claimed[0].attempt_count + 1, _now())
    assert _state(conn, event_id) == "SYNCED"


def test_release_rule_both_branches(conn: sqlite3.Connection) -> None:
    event_id = _enqueue(conn)
    queue = SyncQueue(conn)
    # Never attempted -> back to PENDING.
    queue.claim_due(DEVICE, 10, _now())
    queue.release([event_id], _now())
    assert _state(conn, event_id) == "PENDING"
    # After one failure (attempt_count=1) -> release lands on FAILED.
    claimed = queue.claim_due(DEVICE, 10, _now())
    queue.mark_failed(
        event_id, "boom", claimed[0].attempt_count + 1, _policy(), _now(),
        retry_limit=5,
    )
    future = _now() + timedelta(hours=5)
    claimed = queue.claim_due(DEVICE, 10, future, force=True)
    queue.release([event_id], future)
    assert _state(conn, event_id) == "FAILED"


def test_offline_release_keeps_next_attempt_and_count(
    conn: sqlite3.Connection,
) -> None:
    event_id = _enqueue(conn)
    queue = SyncQueue(conn)
    before = conn.execute(
        "SELECT next_attempt_at FROM sync_queue WHERE event_id = ?", (event_id,)
    ).fetchone()[0]
    queue.claim_due(DEVICE, 10, _now())
    queue.release(
        [event_id], _now(), outcome="OFFLINE", error_code="CONNECTIVITY",
        error_message="offline",
    )
    row = conn.execute(
        "SELECT state, attempt_count, next_attempt_at FROM sync_queue WHERE event_id=?",
        (event_id,),
    ).fetchone()
    assert row[0] == "PENDING"
    assert row[1] == 0
    assert row[2] == before
    attempts = conn.execute(
        "SELECT outcome FROM sync_attempts WHERE event_id = ?", (event_id,)
    ).fetchall()
    assert attempts == [("OFFLINE",)]


def test_mark_failed_dead_letters_at_retry_limit(conn: sqlite3.Connection) -> None:
    event_id = _enqueue(conn)
    queue = SyncQueue(conn)
    now = _now()
    for attempt in range(1, 6):
        now = now + timedelta(hours=attempt)
        queue.claim_due(DEVICE, 10, now, force=True)
        state = queue.mark_failed(
            event_id, "503", attempt, _policy(), now, retry_limit=5
        )
    assert state == "DEAD_LETTER"
    assert _state(conn, event_id) == "DEAD_LETTER"


def test_requeue_dead_resets_to_pending(conn: sqlite3.Connection) -> None:
    event_id = _enqueue(conn)
    queue = SyncQueue(conn)
    queue.claim_due(DEVICE, 10, _now())
    queue.mark_dead(event_id, "rejected", 1, _now(), error_code="VALIDATION_ERROR")
    assert _state(conn, event_id) == "DEAD_LETTER"
    assert queue.requeue_dead(event_id, _now()) == 1
    row = conn.execute(
        "SELECT state, attempt_count FROM sync_queue WHERE event_id = ?",
        (event_id,),
    ).fetchone()
    assert row[0] == "PENDING"
    assert row[1] == 0


def test_recover_stale_counts_as_interrupted(conn: sqlite3.Connection) -> None:
    event_id = _enqueue(conn)
    queue = SyncQueue(conn)
    queue.claim_due(DEVICE, 10, _now())  # row is now SYNCING with claimed_at=_now()
    later = _now() + timedelta(seconds=SYNC_LEASE_SECONDS + 1)
    recovered = queue.recover_stale(DEVICE, later)
    assert recovered == 1
    row = conn.execute(
        "SELECT state, attempt_count FROM sync_queue WHERE event_id = ?",
        (event_id,),
    ).fetchone()
    assert row[0] == "FAILED"
    assert row[1] == 1
    outcomes = conn.execute(
        "SELECT outcome FROM sync_attempts WHERE event_id = ?", (event_id,)
    ).fetchall()
    assert ("INTERRUPTED",) in outcomes


def test_recover_stale_ignores_fresh_lease(conn: sqlite3.Connection) -> None:
    _enqueue(conn)
    queue = SyncQueue(conn)
    queue.claim_due(DEVICE, 10, _now())
    assert queue.recover_stale(DEVICE, _now() + timedelta(seconds=10)) == 0


def test_force_ignores_backoff_not_dead_letter(conn: sqlite3.Connection) -> None:
    event_id = _enqueue(conn)
    queue = SyncQueue(conn)
    queue.claim_due(DEVICE, 10, _now())
    queue.mark_failed(event_id, "boom", 1, _policy(), _now(), retry_limit=5)
    # Not due yet (backoff in the future), but force claims it anyway.
    assert queue.count_due(DEVICE, _now()) == 0
    forced = queue.claim_due(DEVICE, 10, _now(), force=True)
    assert len(forced) == 1


def test_invalid_transition_raises(conn: sqlite3.Connection) -> None:
    event_id = _enqueue(conn)
    queue = SyncQueue(conn)
    # The row is PENDING, not SYNCING: marking it synced is a programming error.
    with pytest.raises(InvalidTransitionError):
        queue.mark_synced([event_id], "ACCEPTED", 1, _now())


def test_stats_and_list(conn: sqlite3.Connection) -> None:
    _enqueue(conn)
    queue = SyncQueue(conn)
    assert queue.stats().get("PENDING") == 1
    rows = queue.list(None, 10)
    assert len(rows) == 1
    assert rows[0]["state"] == "PENDING"
