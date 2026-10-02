"""Sync-queue state machine (design B.9).

``SyncQueue`` owns every transition of a ``sync_queue`` row; callers never write
the ``state`` column directly. States: ``PENDING`` -> ``SYNCING`` ->
(``SYNCED`` | ``FAILED`` | ``DEAD_LETTER``), with ``FAILED`` due again when
``next_attempt_at <= now`` and ``DEAD_LETTER`` reachable only by permanent
rejection or exhausted retries. ``requeue_dead`` moves a dead row back to
``PENDING``.

Crash recovery: at the start of a cycle, rows stuck in ``SYNCING`` with a
``claimed_at`` older than ``SYNC_LEASE_SECONDS`` are treated as an INTERRUPTED
attempt (counted, because the request may have been delivered) and moved on by
the normal fail rule.

Queue ownership: ``claim_due`` and ``recover_stale`` filter ``device_id``; events
left behind by a previous identity are reported separately and never sent under
the wrong envelope. The release rule needs no ``previous_state`` column: a
never-attempted row (``attempt_count == 0``) was ``PENDING``, an attempted one
was ``FAILED``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from agent.sync.retry import BackoffPolicy
from shared.utils.timeutil import parse_iso, to_iso

__all__ = [
    "SYNC_LEASE_SECONDS",
    "InvalidTransitionError",
    "QueuedEvent",
    "SyncQueue",
]

SYNC_LEASE_SECONDS = 300

_ACTIVE_STATES = ("PENDING", "FAILED")


class InvalidTransitionError(Exception):
    """Raised on an attempted state transition that the machine forbids.

    This is a programming error (logged ERROR), not a network condition.
    """


@dataclass(frozen=True)
class QueuedEvent:
    """One claimed queue row, carried through a sync cycle."""

    event_id: str
    run_id: str
    device_id: str
    payload_json: str
    attempt_count: int
    next_attempt_at: str


class SyncQueue:
    """All reads and writes of ``sync_queue`` go through this type."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # -- recovery ---------------------------------------------------------
    def recover_stale(self, device_id: str, now: datetime) -> int:
        """Move expired SYNCING leases on through the fail rule as INTERRUPTED.

        Returns the number of rows recovered.
        """
        now_iso = to_iso(now)
        rows = self._conn.execute(
            """
            SELECT event_id, attempt_count FROM sync_queue
            WHERE device_id = ? AND state = 'SYNCING' AND claimed_at IS NOT NULL
            """,
            (device_id,),
        ).fetchall()
        stale = [
            (str(row[0]), int(row[1]))
            for row in rows
            if self._lease_expired(str(row[0]), now)
        ]
        if not stale:
            return 0
        for event_id, attempt in stale:
            new_count = attempt + 1
            self._record_attempt(
                event_id,
                now_iso,
                outcome="INTERRUPTED",
                error_code="INTERRUPTED",
                error_message="sync lease expired; outcome unknown",
            )
            self._conn.execute(
                """
                UPDATE sync_queue
                SET state = 'FAILED', attempt_count = ?, claimed_at = NULL,
                    updated_at = ?
                WHERE event_id = ?
                """,
                (new_count, now_iso, event_id),
            )
        self._conn.commit()
        return len(stale)

    def _lease_expired(self, event_id: str, now: datetime) -> bool:
        row = self._conn.execute(
            "SELECT claimed_at FROM sync_queue WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        if row is None or row[0] is None:
            return False
        age = (now - parse_iso(str(row[0]))).total_seconds()
        return age >= SYNC_LEASE_SECONDS

    # -- counting / claiming ---------------------------------------------
    def count_due(self, device_id: str, now: datetime, *, force: bool = False) -> int:
        """Return how many events are currently due for ``device_id``."""
        if force:
            return int(
                self._conn.execute(
                    """
                    SELECT COUNT(*) FROM sync_queue
                    WHERE device_id = ? AND state IN ('PENDING','FAILED')
                    """,
                    (device_id,),
                ).fetchone()[0]
            )
        return int(
            self._conn.execute(
                """
                SELECT COUNT(*) FROM sync_queue
                WHERE device_id = ? AND state IN ('PENDING','FAILED')
                  AND next_attempt_at <= ?
                """,
                (device_id, to_iso(now)),
            ).fetchone()[0]
        )

    def claim_due(
        self,
        device_id: str,
        limit: int,
        now: datetime,
        *,
        force: bool = False,
        exclude: frozenset[str] | None = None,
    ) -> list[QueuedEvent]:
        """Atomically claim up to ``limit`` due events for ``device_id``.

        ``force`` ignores ``next_attempt_at`` but never the retry limit (that is
        enforced by the state machine, not here). ``exclude`` skips events
        already handled this cycle, so there is no in-process retry loop even
        under ``force``. Only rows actually updated to SYNCING are returned, so
        concurrent claimers never double-send.
        """
        now_iso = to_iso(now)
        skip = exclude or frozenset()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            if force:
                candidates = self._conn.execute(
                    """
                    SELECT event_id FROM sync_queue
                    WHERE device_id = ? AND state IN ('PENDING','FAILED')
                    ORDER BY next_attempt_at ASC, created_at ASC
                    """,
                    (device_id,),
                ).fetchall()
            else:
                candidates = self._conn.execute(
                    """
                    SELECT event_id FROM sync_queue
                    WHERE device_id = ? AND state IN ('PENDING','FAILED')
                      AND next_attempt_at <= ?
                    ORDER BY next_attempt_at ASC, created_at ASC
                    """,
                    (device_id, now_iso),
                ).fetchall()
            event_ids = [
                str(row[0]) for row in candidates if str(row[0]) not in skip
            ][:limit]
            claimed: list[str] = []
            for event_id in event_ids:
                updated = self._conn.execute(
                    """
                    UPDATE sync_queue
                    SET state = 'SYNCING', claimed_at = ?, updated_at = ?
                    WHERE event_id = ? AND state IN ('PENDING','FAILED')
                    """,
                    (now_iso, now_iso, event_id),
                ).rowcount
                if updated:
                    claimed.append(event_id)
            self._conn.commit()
        except BaseException:
            self._conn.rollback()
            raise
        return [self._load(event_id) for event_id in claimed]

    def _load(self, event_id: str) -> QueuedEvent:
        row = self._conn.execute(
            """
            SELECT event_id, run_id, device_id, payload_json, attempt_count,
                   next_attempt_at
            FROM sync_queue WHERE event_id = ?
            """,
            (event_id,),
        ).fetchone()
        if row is None:
            raise InvalidTransitionError(f"claimed event vanished: {event_id}")
        return QueuedEvent(
            event_id=str(row[0]),
            run_id=str(row[1]),
            device_id=str(row[2]),
            payload_json=str(row[3]),
            attempt_count=int(row[4]),
            next_attempt_at=str(row[5]),
        )

    # -- terminal / failure transitions ----------------------------------
    def mark_synced(
        self, event_ids: list[str], outcome: str, attempt: int, now: datetime
    ) -> None:
        """Move claimed rows to the terminal SYNCED state (accepted/duplicate)."""
        now_iso = to_iso(now)
        for event_id in event_ids:
            self._require_state(event_id, "SYNCING")
            self._record_attempt(
                event_id, now_iso, outcome=outcome, error_code=None, error_message=None
            )
            self._conn.execute(
                """
                UPDATE sync_queue
                SET state = 'SYNCED', attempt_count = ?, claimed_at = NULL,
                    synced_at = ?, updated_at = ?, last_error = NULL
                WHERE event_id = ?
                """,
                (attempt, now_iso, now_iso, event_id),
            )
        self._conn.commit()

    def mark_failed(
        self,
        event_id: str,
        error: str,
        attempt: int,
        policy: BackoffPolicy,
        now: datetime,
        *,
        retry_limit: int,
        outcome: str = "TRANSIENT_ERROR",
        error_code: str | None = None,
        http_status: int | None = None,
    ) -> str:
        """Record a transient failure. Returns the resulting state.

        ``attempt`` is the new attempt count (count already incremented). The row
        becomes DEAD_LETTER when ``attempt >= retry_limit``, else FAILED with a
        backoff ``next_attempt_at``.
        """
        self._require_state(event_id, "SYNCING")
        now_iso = to_iso(now)
        if attempt >= retry_limit:
            self._record_attempt(
                event_id,
                now_iso,
                outcome=outcome,
                error_code=error_code,
                error_message=error,
                http_status=http_status,
            )
            self._conn.execute(
                """
                UPDATE sync_queue
                SET state = 'DEAD_LETTER', attempt_count = ?, claimed_at = NULL,
                    updated_at = ?, last_error = ?
                WHERE event_id = ?
                """,
                (attempt, now_iso, error, event_id),
            )
            self._conn.commit()
            return "DEAD_LETTER"
        delay = policy.delay(attempt)
        next_at = to_iso(now + timedelta(seconds=delay))
        self._record_attempt(
            event_id,
            now_iso,
            outcome=outcome,
            error_code=error_code,
            error_message=error,
            http_status=http_status,
        )
        self._conn.execute(
            """
            UPDATE sync_queue
            SET state = 'FAILED', attempt_count = ?, claimed_at = NULL,
                next_attempt_at = ?, updated_at = ?, last_error = ?
            WHERE event_id = ?
            """,
            (attempt, next_at, now_iso, error, event_id),
        )
        self._conn.commit()
        return "FAILED"

    def mark_dead(
        self,
        event_id: str,
        error: str,
        attempt: int,
        now: datetime,
        *,
        outcome: str = "REJECTED",
        error_code: str | None = None,
        http_status: int | None = None,
    ) -> None:
        """Move a claimed row to DEAD_LETTER by permanent rejection."""
        self._require_state(event_id, "SYNCING")
        now_iso = to_iso(now)
        self._record_attempt(
            event_id,
            now_iso,
            outcome=outcome,
            error_code=error_code,
            error_message=error,
            http_status=http_status,
        )
        self._conn.execute(
            """
            UPDATE sync_queue
            SET state = 'DEAD_LETTER', attempt_count = ?, claimed_at = NULL,
                updated_at = ?, last_error = ?
            WHERE event_id = ?
            """,
            (attempt, now_iso, error, event_id),
        )
        self._conn.commit()

    def release(
        self,
        event_ids: list[str],
        now: datetime,
        *,
        outcome: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        http_status: int | None = None,
    ) -> None:
        """Release claimed rows without counting an attempt (release rule).

        ``attempt_count == 0`` returns to PENDING, otherwise FAILED;
        ``next_attempt_at`` is unchanged. An optional attempt row (e.g. OFFLINE,
        CONFIG_ERROR, AUTH_ERROR) is recorded for visibility.
        """
        now_iso = to_iso(now)
        for event_id in event_ids:
            self._require_state(event_id, "SYNCING")
            if outcome is not None:
                self._record_attempt(
                    event_id,
                    now_iso,
                    outcome=outcome,
                    error_code=error_code,
                    error_message=error_message,
                    http_status=http_status,
                )
            self._conn.execute(
                """
                UPDATE sync_queue
                SET state = CASE WHEN attempt_count = 0
                                 THEN 'PENDING' ELSE 'FAILED' END,
                    claimed_at = NULL, updated_at = ?
                WHERE event_id = ? AND state = 'SYNCING'
                """,
                (now_iso, event_id),
            )
        self._conn.commit()

    def requeue_dead(self, event_id: str | None, now: datetime) -> int:
        """Reset DEAD_LETTER rows to PENDING with ``attempt_count = 0``.

        ``event_id`` requeues one row; ``None`` requeues every dead row. Returns
        the number of rows affected.
        """
        now_iso = to_iso(now)
        if event_id is None:
            cursor = self._conn.execute(
                """
                UPDATE sync_queue
                SET state = 'PENDING', attempt_count = 0, next_attempt_at = ?,
                    claimed_at = NULL, updated_at = ?, last_error = NULL
                WHERE state = 'DEAD_LETTER'
                """,
                (now_iso, now_iso),
            )
        else:
            cursor = self._conn.execute(
                """
                UPDATE sync_queue
                SET state = 'PENDING', attempt_count = 0, next_attempt_at = ?,
                    claimed_at = NULL, updated_at = ?, last_error = NULL
                WHERE state = 'DEAD_LETTER' AND event_id = ?
                """,
                (now_iso, now_iso, event_id),
            )
        self._conn.commit()
        return int(cursor.rowcount)

    # -- reporting --------------------------------------------------------
    def stats(self) -> dict[str, int]:
        """Return a mapping of state -> count over the whole queue."""
        counts: dict[str, int] = {}
        for state, count in self._conn.execute(
            "SELECT state, COUNT(*) FROM sync_queue GROUP BY state"
        ).fetchall():
            counts[str(state)] = int(count)
        return counts

    def other_device_pending(self, device_id: str) -> int:
        """Count non-terminal events owned by a different identity."""
        return int(
            self._conn.execute(
                """
                SELECT COUNT(*) FROM sync_queue
                WHERE device_id != ? AND state IN ('PENDING','FAILED','SYNCING')
                """,
                (device_id,),
            ).fetchone()[0]
        )

    def list(self, state: str | None, limit: int) -> list[dict[str, object]]:
        """Return queue rows (optionally filtered by state) for ``queue list``."""
        if state is not None:
            rows = self._conn.execute(
                """
                SELECT event_id, device_id, state, attempt_count, next_attempt_at,
                       last_error, updated_at
                FROM sync_queue WHERE state = ?
                ORDER BY updated_at DESC LIMIT ?
                """,
                (state, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT event_id, device_id, state, attempt_count, next_attempt_at,
                       last_error, updated_at
                FROM sync_queue
                ORDER BY updated_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "event_id": str(r[0]),
                "device_id": str(r[1]),
                "state": str(r[2]),
                "attempt_count": int(r[3]),
                "next_attempt_at": str(r[4]),
                "last_error": r[5],
                "updated_at": str(r[6]),
            }
            for r in rows
        ]

    # -- internals --------------------------------------------------------
    def _require_state(self, event_id: str, expected: str) -> None:
        row = self._conn.execute(
            "SELECT state FROM sync_queue WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        if row is None:
            raise InvalidTransitionError(f"no such event: {event_id}")
        current = str(row[0])
        if current != expected:
            raise InvalidTransitionError(
                f"event {event_id} is {current}, expected {expected}"
            )

    def _record_attempt(
        self,
        event_id: str,
        attempted_at: str,
        *,
        outcome: str,
        error_code: str | None,
        error_message: str | None,
        http_status: int | None = None,
        request_id: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO sync_attempts (
                event_id, attempted_at, outcome, http_status, error_code,
                error_message, duration_ms, request_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                attempted_at,
                outcome,
                http_status,
                error_code,
                error_message,
                duration_ms,
                request_id,
            ),
        )
