"""SyncService.run_cycle tests (design B.9): the acceptance scenarios."""

from __future__ import annotations

import random
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent.config.settings import Settings, load_settings
from agent.storage import local_db
from agent.storage.local_db import LocalStore
from agent.sync.client import (
    DeviceNotRegisteredError,
    ItemResult,
    OfflineError,
    PayloadTooLargeError,
    PermanentSyncError,
    RegistrationResult,
    TelemetryResult,
    TransientSyncError,
)
from agent.sync.service import SyncService
from shared.models.diagnostic import (
    DiagnosticResult,
    HealthStatus,
    NetworkStatus,
    RunSource,
)
from shared.utils.ids import new_uuid7
from shared.utils.timeutil import to_iso

DEVICE = "demo-device-0001"


class _FakeClient:
    """A scripted ApiClient stand-in: queues of send/register behaviors."""

    def __init__(self) -> None:
        self.send_script: list = []
        self.register_script: list = []
        self.sent: list[list[dict]] = []
        self.registers = 0

    def register_device(self, payload: dict) -> RegistrationResult:
        self.registers += 1
        if self.register_script:
            behavior = self.register_script.pop(0)
            if isinstance(behavior, Exception):
                raise behavior
        return RegistrationResult(device_id=DEVICE, created=True)

    def send_telemetry(self, device_id: str, events: list[dict]) -> TelemetryResult:
        self.sent.append(events)
        behavior = self.send_script.pop(0) if self.send_script else "accept_all"
        if isinstance(behavior, Exception):
            raise behavior
        if behavior == "accept_all":
            return TelemetryResult(
                results=[
                    ItemResult(event_id=e["event_id"], status="accepted")
                    for e in events
                ]
            )
        if callable(behavior):
            return behavior(events)
        raise AssertionError(f"unknown behavior {behavior!r}")


def _settings() -> Settings:
    return load_settings(
        env={
            "API_BASE_URL": "https://api.example",
            "AGENT_API_KEY": "k" * 32,
            "DEVICE_ID": DEVICE,
        }
    )


def _service(
    conn: sqlite3.Connection, client: _FakeClient, now: datetime
) -> SyncService:
    return SyncService(
        conn,
        _settings(),
        client,  # type: ignore[arg-type]
        device_id=DEVICE,
        rng=random.Random(1),
        now=lambda: now,
    )


def _result() -> DiagnosticResult:
    now = to_iso(datetime.now(UTC))
    return DiagnosticResult(
        run_id=new_uuid7(),
        device_id=DEVICE,
        started_at=now,
        finished_at=now,
        source=RunSource.LIVE,
        status=HealthStatus.HEALTHY,
        network_status=NetworkStatus.HEALTHY,
        checks=(),
        alerts=(),
        metrics=(),
        facts={
            "cpu": {"model": "CPU", "logical_cpus": 8, "physical_cores": 4},
            "system": {
                "os_name": "Windows",
                "os_version": "10.0.22631",
                "architecture": "AMD64",
            },
            "memory": {"total_bytes": 8589934592},
        },
    )


def _enqueue(conn: sqlite3.Connection, count: int = 1) -> list[str]:
    ids: list[str] = []
    store = LocalStore(conn)
    for _ in range(count):
        result = _result()
        store.save_run(result, enqueue_event=True)
        row = conn.execute(
            "SELECT event_id FROM sync_queue WHERE run_id = ?", (result.run_id,)
        ).fetchone()
        ids.append(str(row[0]))
    return ids


def _state(conn: sqlite3.Connection, event_id: str) -> str:
    return str(
        conn.execute(
            "SELECT state FROM sync_queue WHERE event_id = ?", (event_id,)
        ).fetchone()[0]
    )


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = local_db.connect(tmp_path / "agent.db")
    connection.execute(
        """
        INSERT INTO devices (device_id, device_name, hostname, is_local, created_at)
        VALUES (?, ?, ?, 0, ?)
        """,
        (DEVICE, "DEMO-PC", "host", to_iso(datetime.now(UTC))),
    )
    connection.commit()
    yield connection
    connection.close()


def _now() -> datetime:
    return datetime.now(UTC) + timedelta(seconds=5)


# --- scenarios ---------------------------------------------------------------
def test_happy_path_marks_synced(conn: sqlite3.Connection) -> None:
    event_id = _enqueue(conn)[0]
    client = _FakeClient()
    report = _service(conn, client, _now()).run_cycle()
    assert _state(conn, event_id) == "SYNCED"
    assert report.accepted == 1
    assert not report.had_failure


def test_offline_keeps_pending_count_zero_and_aborts(
    conn: sqlite3.Connection,
) -> None:
    event_id = _enqueue(conn)[0]
    client = _FakeClient()
    client.send_script = [OfflineError("dns")]
    report = _service(conn, client, _now()).run_cycle()
    row = conn.execute(
        "SELECT state, attempt_count FROM sync_queue WHERE event_id = ?",
        (event_id,),
    ).fetchone()
    assert row[0] == "PENDING"
    assert row[1] == 0
    assert report.aborted == "offline"
    assert report.had_failure  # exit 3


def test_offline_then_connectivity_syncs(conn: sqlite3.Connection) -> None:
    event_id = _enqueue(conn)[0]
    client = _FakeClient()
    client.send_script = [OfflineError("dns")]
    _service(conn, client, _now()).run_cycle()
    assert _state(conn, event_id) == "PENDING"
    # Next cycle, connectivity returns.
    client.send_script = ["accept_all"]
    _service(conn, client, _now()).run_cycle()
    assert _state(conn, event_id) == "SYNCED"


def test_503_dead_letters_after_retry_limit(conn: sqlite3.Connection) -> None:
    event_id = _enqueue(conn)[0]
    client = _FakeClient()
    now = _now()
    for cycle in range(1, 6):
        client.send_script = [TransientSyncError("503", http_status=503)]
        _service(conn, client, now).run_cycle(force=True)
        now = now + timedelta(hours=cycle)
    assert _state(conn, event_id) == "DEAD_LETTER"


def test_duplicate_marks_synced(conn: sqlite3.Connection) -> None:
    event_id = _enqueue(conn)[0]
    client = _FakeClient()
    client.send_script = [
        lambda events: TelemetryResult(
            results=[ItemResult(event_id=events[0]["event_id"], status="duplicate")]
        )
    ]
    report = _service(conn, client, _now()).run_cycle()
    assert _state(conn, event_id) == "SYNCED"
    assert report.duplicates == 1


def test_event_id_conflict_dead_letters(conn: sqlite3.Connection) -> None:
    event_id = _enqueue(conn)[0]
    client = _FakeClient()
    client.send_script = [
        lambda events: TelemetryResult(
            results=[
                ItemResult(
                    event_id=events[0]["event_id"],
                    status="rejected",
                    code="EVENT_ID_CONFLICT",
                )
            ]
        )
    ]
    _service(conn, client, _now()).run_cycle()
    assert _state(conn, event_id) == "DEAD_LETTER"


def test_clock_skew_item_is_transient(conn: sqlite3.Connection) -> None:
    event_id = _enqueue(conn)[0]
    client = _FakeClient()
    client.send_script = [
        lambda events: TelemetryResult(
            results=[
                ItemResult(
                    event_id=events[0]["event_id"],
                    status="rejected",
                    code="CLOCK_SKEW",
                )
            ]
        )
    ]
    report = _service(conn, client, _now()).run_cycle()
    assert _state(conn, event_id) == "FAILED"
    assert report.failed == 1


def test_single_event_413_dead_letters(conn: sqlite3.Connection) -> None:
    event_id = _enqueue(conn)[0]
    client = _FakeClient()
    client.send_script = [PermanentSyncError("too large", code="PAYLOAD_TOO_LARGE")]
    _service(conn, client, _now()).run_cycle()
    assert _state(conn, event_id) == "DEAD_LETTER"


def test_multi_event_413_resends_one_at_a_time(conn: sqlite3.Connection) -> None:
    ids = _enqueue(conn, count=2)
    client = _FakeClient()
    # First send (the batch) -> 413; then two single-event sends succeed.
    client.send_script = [
        PayloadTooLargeError("too large"),
        "accept_all",
        "accept_all",
    ]
    _service(conn, client, _now()).run_cycle()
    for event_id in ids:
        assert _state(conn, event_id) == "SYNCED"
    # One batch request plus two single-event requests.
    assert len(client.sent) == 3


def test_409_reregisters_then_resends(conn: sqlite3.Connection) -> None:
    event_id = _enqueue(conn)[0]
    client = _FakeClient()
    client.send_script = [DeviceNotRegisteredError("not registered"), "accept_all"]
    report = _service(conn, client, _now()).run_cycle()
    assert _state(conn, event_id) == "SYNCED"
    assert client.registers >= 1
    assert report.accepted == 1


def test_disabled_when_not_configured(conn: sqlite3.Connection) -> None:
    _enqueue(conn)
    settings = load_settings(env={})  # no API_BASE_URL
    service = SyncService(
        conn, settings, _FakeClient(), device_id=DEVICE,  # type: ignore[arg-type]
        now=_now,
    )
    report = service.run_cycle()
    assert report.disabled


def test_no_due_events_returns_without_network(conn: sqlite3.Connection) -> None:
    client = _FakeClient()
    report = _service(conn, client, _now()).run_cycle()
    assert client.sent == []
    assert not report.had_failure
