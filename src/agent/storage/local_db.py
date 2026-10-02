"""Local SQLite database: connection, migrations and run persistence.

``connect(path, read_only=...)`` is the single entry point for opening the
local database. Writable connections (``scan``, ``run``, ``sync``,
``queue requeue``, ``demo``) create the parent directory, enable WAL and
foreign keys, and apply migrations keyed by ``PRAGMA user_version``. Read-only
connections (``hardware``, ``network``, ``health``, ``status``, ``queue
list``/``stats``) open a ``mode=ro`` URI, never migrate and never change a
PRAGMA; an outdated schema raises ``SchemaOutdatedError`` (design B.8).

Migration v1 marks the database with ``PRAGMA application_id`` so the ``demo``
command can refuse to delete a file it did not create (review M1): demo DBs get
``DEMO_DB_APPLICATION_ID`` and live DBs get ``LIVE_DB_APPLICATION_ID``.

``LocalStore.save_run`` writes the run, its results and (optionally) the queue
event inside one ``BEGIN IMMEDIATE`` transaction, so the invariant "a persisted
run that should sync always has a queue event, and a queued event always has
its run" is owned by the storage layer.
"""

from __future__ import annotations

import json
import sqlite3
import urllib.parse
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from shared.models.diagnostic import DiagnosticResult, RunSource
from shared.utils.ids import new_uuid7
from shared.utils.timeutil import to_iso, utc_now

__all__ = [
    "StorageError",
    "SchemaOutdatedError",
    "LocalStore",
    "connect",
    "SCHEMA_VERSION",
    "DEMO_DB_APPLICATION_ID",
    "LIVE_DB_APPLICATION_ID",
]

SCHEMA_VERSION = 1

# ASCII "L2CD" (Local-to-Cloud Diagnostic). A fixed marker written into the
# SQLite header so the demo command never deletes a file it did not create.
DEMO_DB_APPLICATION_ID = 0x4C324344
# Live databases get a distinct marker, so a copied live DB also fails the
# demo equality check.
LIVE_DB_APPLICATION_ID = 0x4C324C56  # "L2LV"

_BUSY_TIMEOUT_MS = 5000
_CONNECT_TIMEOUT_S = 5


class StorageError(Exception):
    """Raised when a SQLite operation fails; wraps the underlying error."""


class SchemaOutdatedError(StorageError):
    """Raised when a read-only connection finds an older ``user_version``."""


_SCHEMA_V1 = """
CREATE TABLE devices (
  device_id TEXT PRIMARY KEY,
  device_name TEXT NOT NULL,
  hostname TEXT NOT NULL,
  is_local INTEGER NOT NULL DEFAULT 1 CHECK (is_local IN (0,1)),
  created_at TEXT NOT NULL,
  registration_fingerprint TEXT,
  registered_at TEXT
);
CREATE UNIQUE INDEX idx_devices_single_local ON devices(is_local) WHERE is_local = 1;
CREATE TABLE diagnostic_runs (
  run_id TEXT PRIMARY KEY,
  device_id TEXT NOT NULL REFERENCES devices(device_id),
  source TEXT NOT NULL CHECK (source IN ('live','demo')),
  scenario TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT NOT NULL,
  status TEXT NOT NULL,
  network_status TEXT NOT NULL,
  result_json TEXT NOT NULL
);
CREATE INDEX idx_runs_device_started ON diagnostic_runs(device_id, started_at DESC);
CREATE TABLE diagnostic_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES diagnostic_runs(run_id) ON DELETE CASCADE,
  result_type TEXT NOT NULL CHECK (result_type IN ('check','alert','metric')),
  name TEXT NOT NULL,
  status TEXT,
  value REAL,
  unit TEXT,
  subject TEXT,
  details_json TEXT NOT NULL
);
CREATE INDEX idx_results_run ON diagnostic_results(run_id);
CREATE INDEX idx_results_name ON diagnostic_results(result_type, name);
CREATE TABLE sync_queue (
  event_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL UNIQUE REFERENCES diagnostic_runs(run_id),
  device_id TEXT NOT NULL REFERENCES devices(device_id),
  event_type TEXT NOT NULL DEFAULT 'diagnostic_run',
  payload_json TEXT NOT NULL,
  state TEXT NOT NULL CHECK (
    state IN ('PENDING','SYNCING','SYNCED','FAILED','DEAD_LETTER')
  ),
  attempt_count INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TEXT NOT NULL,
  claimed_at TEXT,
  last_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  synced_at TEXT
);
CREATE INDEX idx_queue_device_state_next
  ON sync_queue(device_id, state, next_attempt_at);
CREATE TABLE sync_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL REFERENCES sync_queue(event_id),
  attempted_at TEXT NOT NULL,
  outcome TEXT NOT NULL CHECK (
    outcome IN (
      'ACCEPTED','DUPLICATE','REJECTED','TRANSIENT_ERROR',
      'OFFLINE','AUTH_ERROR','CONFIG_ERROR','INTERRUPTED'
    )
  ),
  http_status INTEGER,
  error_code TEXT,
  error_message TEXT,
  duration_ms INTEGER,
  request_id TEXT
);
CREATE INDEX idx_attempts_event ON sync_attempts(event_id);
"""


def connect(
    path: Path, *, read_only: bool = False, demo: bool = False
) -> sqlite3.Connection:
    """Open the local database.

    Writable mode creates parent directories, enables WAL and foreign keys and
    applies pending migrations. ``demo`` selects the application-id marker used
    by migration v1 (ignored for an already-migrated or read-only database).
    Read-only mode opens a ``mode=ro`` URI, applies no migration and changes no
    PRAGMA; an older ``user_version`` raises ``SchemaOutdatedError``.
    """
    if read_only:
        return _connect_read_only(path)
    return _connect_writable(path, demo=demo)


def _connect_writable(path: Path, *, demo: bool) -> sqlite3.Connection:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=_CONNECT_TIMEOUT_S)
    except (sqlite3.Error, OSError) as exc:
        raise StorageError(f"cannot open database {path}: {exc}") from exc
    try:
        conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        _migrate(conn, demo=demo)
    except sqlite3.Error as exc:
        conn.close()
        raise StorageError(f"cannot initialize database {path}: {exc}") from exc
    return conn


def _connect_read_only(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise StorageError(f"database file does not exist: {path}")
    quoted = urllib.parse.quote(path.as_posix())
    uri = f"file:{quoted}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=_CONNECT_TIMEOUT_S)
        conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    except sqlite3.Error as exc:
        raise StorageError(f"cannot open database {path}: {exc}") from exc
    if version < SCHEMA_VERSION:
        conn.close()
        raise SchemaOutdatedError(
            f"schema version {version} is older than {SCHEMA_VERSION}"
        )
    return conn


def _migrate(conn: sqlite3.Connection, *, demo: bool) -> None:
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version >= SCHEMA_VERSION:
        return
    if version == 0:
        application_id = DEMO_DB_APPLICATION_ID if demo else LIVE_DB_APPLICATION_ID
        with conn:
            conn.executescript(_SCHEMA_V1)
            conn.execute(f"PRAGMA application_id = {application_id}")
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def read_application_id(path: Path) -> int | None:
    """Return the ``application_id`` of a SQLite file, or None if unreadable."""
    if not path.is_file():
        return None
    quoted = urllib.parse.quote(path.as_posix())
    uri = f"file:{quoted}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=_CONNECT_TIMEOUT_S)
    except sqlite3.Error:
        return None
    try:
        return int(conn.execute("PRAGMA application_id").fetchone()[0])
    except sqlite3.Error:
        return None
    finally:
        conn.close()


class LocalStore:
    """Persists diagnostic runs and enqueues sync events transactionally."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def save_run(self, result: DiagnosticResult, *, enqueue_event: bool) -> None:
        """Insert the run, its results and (optionally) a queue event atomically.

        ``result.device_id`` must be set (the pipeline enforces this). The queue
        payload is frozen here so later retries send byte-identical JSON.
        """
        if result.device_id is None:
            raise StorageError("cannot persist a run without a device_id")
        try:
            with self._transaction():
                self._insert_run(result)
                self._insert_results(result)
                if enqueue_event:
                    self._enqueue(result)
        except sqlite3.Error as exc:
            raise StorageError(f"failed to save run: {exc}") from exc

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._conn.rollback()
            raise
        else:
            self._conn.commit()

    def _insert_run(self, result: DiagnosticResult) -> None:
        scenario = (
            result.facts.get("scenario")
            if result.source is RunSource.DEMO
            else None
        )
        self._conn.execute(
            """
            INSERT INTO diagnostic_runs (
                run_id, device_id, source, scenario, started_at, finished_at,
                status, network_status, result_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.run_id,
                result.device_id,
                result.source.value,
                scenario,
                result.started_at,
                result.finished_at,
                result.status.value,
                result.network_status.value,
                json.dumps(result.to_dict(), sort_keys=True),
            ),
        )

    def _insert_results(self, result: DiagnosticResult) -> None:
        ResultRow = tuple[
            str, str, str, str | None, float | None, str | None, str | None, str
        ]
        rows: list[ResultRow] = []
        for check in result.checks:
            rows.append(
                (
                    result.run_id,
                    "check",
                    check.name,
                    check.status.value,
                    None,
                    None,
                    None,
                    json.dumps(check.to_dict(), sort_keys=True),
                )
            )
        for alert in result.alerts:
            rows.append(
                (
                    result.run_id,
                    "alert",
                    alert.rule_id,
                    alert.severity.value,
                    None,
                    None,
                    alert.subject,
                    json.dumps(alert.to_dict(), sort_keys=True),
                )
            )
        for metric in result.metrics:
            rows.append(
                (
                    result.run_id,
                    "metric",
                    metric.name,
                    None,
                    metric.value,
                    metric.unit,
                    metric.labels.get("volume"),
                    json.dumps(metric.to_dict(), sort_keys=True),
                )
            )
        self._conn.executemany(
            """
            INSERT INTO diagnostic_results (
                run_id, result_type, name, status, value, unit, subject, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    def _enqueue(self, result: DiagnosticResult) -> None:
        now = to_iso(utc_now())
        event_id = new_uuid7()
        payload = {
            "event_id": event_id,
            "event_type": "diagnostic_run",
            "run_id": result.run_id,
            "device_id": result.device_id,
            "result": result.to_dict(),
        }
        self._conn.execute(
            """
            INSERT INTO sync_queue (
                event_id, run_id, device_id, event_type, payload_json, state,
                attempt_count, next_attempt_at, created_at, updated_at
            ) VALUES (?, ?, ?, 'diagnostic_run', ?, 'PENDING', 0, ?, ?, ?)
            """,
            (
                event_id,
                result.run_id,
                result.device_id,
                json.dumps(payload, sort_keys=True),
                now,
                now,
                now,
            ),
        )
