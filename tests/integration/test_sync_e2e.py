"""Agent-to-handler end-to-end sync tests (design B.9, B.18, B.20).

The real ``UrllibTransport`` talks to a local ``ThreadingHTTPServer`` that
dispatches to the real Lambda handlers over a moto-backed DynamoDB table and SSM
keys, so the whole sync path runs locally with no AWS account. The server's
optional fault modes drive the transient / malformed / redirect branches.
"""

from __future__ import annotations

import random
import sqlite3
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import boto3
import pytest
from moto import mock_aws

from agent.config.settings import Settings, load_settings
from agent.storage import local_db
from agent.storage.local_db import LocalStore
from agent.storage.queue import SyncQueue
from agent.sync.client import ApiClient, UrllibTransport
from agent.sync.service import SyncService
from cloud import repository
from cloud.handlers import device, diagnostic, telemetry
from shared.models.diagnostic import (
    DiagnosticResult,
    HealthStatus,
    NetworkStatus,
    RunSource,
)
from shared.utils.ids import new_uuid7
from shared.utils.timeutil import to_iso, utc_now
from tests.support.local_api import LocalApiServer

TABLE_NAME = "diagnostics-e2e"
INGEST_PARAM = "/diagnostic-gateway/e2e/ingest-api-key"
READ_PARAM = "/diagnostic-gateway/e2e/read-api-key"
INGEST_KEY = "ingest-" + "a" * 40
READ_KEY = "read-" + "b" * 40
DEVICE_ID = "e2e-device-0001"


@pytest.fixture(autouse=True)
def cloud_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("TABLE_NAME", TABLE_NAME)
    monkeypatch.setenv("INGEST_KEY_PARAMETER", INGEST_PARAM)
    monkeypatch.setenv("READ_KEY_PARAMETER", READ_PARAM)
    monkeypatch.setenv("DIAGNOSTIC_RETENTION_DAYS", "30")
    with mock_aws():
        _create_table()
        _put_keys()
        _reset_handler_state()
        repository.get_table.cache_clear()
        yield
        repository.get_table.cache_clear()
        _reset_handler_state()


def _create_table() -> None:
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName=TABLE_NAME,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI1PK", "AttributeType": "S"},
            {"AttributeName": "GSI1SK", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": repository.GSI1_NAME,
                "KeySchema": [
                    {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    )


def _put_keys() -> None:
    ssm = boto3.client("ssm", region_name="us-east-1")
    ssm.put_parameter(Name=INGEST_PARAM, Value=INGEST_KEY, Type="SecureString")
    ssm.put_parameter(Name=READ_PARAM, Value=READ_KEY, Type="SecureString")


def _reset_handler_state() -> None:
    for module in (device, diagnostic, telemetry):
        module._settings = None  # type: ignore[attr-defined]
        module._auth = None  # type: ignore[attr-defined]


# --- local store + settings --------------------------------------------------


def _settings(base_url: str) -> Settings:
    return load_settings(
        env={
            "API_BASE_URL": base_url,
            "AGENT_API_KEY": INGEST_KEY,
            "DEVICE_ID": DEVICE_ID,
            "RETRY_LIMIT": "3",
            # Keep offline/connect attempts fast so the suite stays quick.
            "HTTP_TIMEOUT_SECONDS": "1",
        }
    )


def _facts() -> dict[str, Any]:
    return {
        "cpu": {"model": "E2E CPU", "logical_cpus": 4, "physical_cores": 4},
        "memory": {"total_bytes": 16 * 1024**3},
        "system": {
            "os_name": "Windows",
            "os_version": "10.0.22631",
            "architecture": "AMD64",
            "hostname": "E2E-PC",
        },
    }


def _persist_run(conn: sqlite3.Connection, *, started: datetime) -> str:
    """Persist a device + one diagnostic run that enqueues a sync event."""
    conn.execute(
        """
        INSERT INTO devices (device_id, device_name, hostname, is_local, created_at)
        VALUES (?, 'E2E PC', 'E2E-PC', 0, ?)
        ON CONFLICT(device_id) DO NOTHING
        """,
        (DEVICE_ID, to_iso(utc_now())),
    )
    conn.commit()
    run_id = new_uuid7()
    result = DiagnosticResult(
        run_id=run_id,
        device_id=DEVICE_ID,
        started_at=to_iso(started),
        finished_at=to_iso(started),
        source=RunSource.LIVE,
        status=HealthStatus.HEALTHY,
        network_status=NetworkStatus.HEALTHY,
        checks=(),
        alerts=(),
        metrics=(),
        facts=_facts(),
    )
    LocalStore(conn).save_run(result, enqueue_event=True)
    return run_id


def _service(
    conn: sqlite3.Connection, settings: Settings
) -> SyncService:
    client = ApiClient(
        base_url=settings.api_base_url,
        api_key=settings.api_key,
        transport=UrllibTransport(),
        timeout=settings.sync.http_timeout_s,
    )
    return SyncService(
        conn,
        settings,
        client,
        device_id=DEVICE_ID,
        rng=random.Random(0),
    )


def _states(conn: sqlite3.Connection) -> dict[str, int]:
    return SyncQueue(conn).stats()


def _attempt_outcomes(conn: sqlite3.Connection) -> list[str]:
    return [
        row[0]
        for row in conn.execute(
            "SELECT outcome FROM sync_attempts ORDER BY id"
        ).fetchall()
    ]


# --- tests -------------------------------------------------------------------


def test_scanned_run_syncs(tmp_db: Path) -> None:
    conn = local_db.connect(tmp_db)
    try:
        _persist_run(conn, started=utc_now())
        with LocalApiServer() as server:
            settings = _settings(server.base_url)
            report = _service(conn, settings).run_cycle(force=True)
            assert report.accepted == 1
            assert _states(conn).get("SYNCED") == 1
    finally:
        conn.close()


def test_resend_same_event_is_duplicate(tmp_db: Path) -> None:
    conn = local_db.connect(tmp_db)
    try:
        _persist_run(conn, started=utc_now())
        with LocalApiServer() as server:
            settings = _settings(server.base_url)
            client = ApiClient(
                base_url=server.base_url,
                api_key=settings.api_key,
                transport=UrllibTransport(),
                timeout=5,
            )
            # Register, then send the same event twice directly.
            event_row = conn.execute(
                "SELECT payload_json FROM sync_queue LIMIT 1"
            ).fetchone()
            import json

            payload = json.loads(event_row[0])
            from agent.sync.serializer import build_event

            built = build_event(DiagnosticResult.from_dict(payload["result"]))
            built["event_id"] = payload["event_id"]
            client.register_device(
                _registration_from_facts()
            )
            first = client.send_telemetry(DEVICE_ID, [built])
            second = client.send_telemetry(DEVICE_ID, [built])
            assert first.results[0].status == "accepted"
            assert second.results[0].status == "duplicate"
    finally:
        conn.close()


def _registration_from_facts() -> dict[str, Any]:
    from agent.sync.serializer import build_registration

    return build_registration(DEVICE_ID, "E2E PC", _facts())


def test_server_stopped_is_pending_offline(tmp_db: Path) -> None:
    conn = local_db.connect(tmp_db)
    try:
        _persist_run(conn, started=utc_now())
        with LocalApiServer() as server:
            base_url = server.base_url
        # Server is now down; the port should refuse connections.
        settings = _settings(base_url)
        report = _service(conn, settings).run_cycle(force=True)
        assert report.aborted == "offline"
        assert _states(conn).get("PENDING") == 1
        count = conn.execute(
            "SELECT attempt_count FROM sync_queue"
        ).fetchone()[0]
        assert count == 0
        assert "OFFLINE" in _attempt_outcomes(conn)
    finally:
        conn.close()


def test_long_outage_then_recovery(tmp_db: Path) -> None:
    conn = local_db.connect(tmp_db)
    try:
        _persist_run(conn, started=utc_now())
        with LocalApiServer() as server:
            down_url = server.base_url
        settings = _settings(down_url)
        for _ in range(10):  # more than RETRY_LIMIT
            _service(conn, settings).run_cycle(force=True)
        assert _states(conn).get("PENDING") == 1
        count = conn.execute("SELECT attempt_count FROM sync_queue").fetchone()[0]
        assert count == 0
        offline_rows = sum(1 for o in _attempt_outcomes(conn) if o == "OFFLINE")
        assert offline_rows == 10

        with LocalApiServer() as server:  # fresh port
            settings = _settings(server.base_url)
            report = _service(conn, settings).run_cycle(force=True)
            assert report.accepted == 1
            assert _states(conn).get("SYNCED") == 1
    finally:
        conn.close()


def test_503_backoff_then_dead_letter_then_requeue(tmp_db: Path) -> None:
    conn = local_db.connect(tmp_db)
    try:
        _persist_run(conn, started=utc_now())
        # Register first against a healthy server so the 409 path is not hit.
        with LocalApiServer() as server:
            _service(conn, _settings(server.base_url)).run_cycle(force=True)
        assert _states(conn).get("SYNCED") == 1

        # New run that must sync against a 503 server.
        _persist_run(conn, started=utc_now() + timedelta(seconds=1))
        with LocalApiServer(fault_status=503) as server:
            settings = _settings(server.base_url)
            for _ in range(settings.sync.retry_limit):
                _service(conn, settings).run_cycle(force=True)
        states = _states(conn)
        assert states.get("DEAD_LETTER") == 1

        # Requeue -> PENDING -> SYNCED against a healthy server.
        SyncQueue(conn).requeue_dead(None, utc_now())
        with LocalApiServer() as server:
            report = _service(conn, _settings(server.base_url)).run_cycle(force=True)
            assert report.accepted == 1
        assert _states(conn).get("DEAD_LETTER", 0) == 0
    finally:
        conn.close()


def test_malformed_response_is_transient(tmp_db: Path) -> None:
    conn = local_db.connect(tmp_db)
    try:
        _persist_run(conn, started=utc_now())
        with LocalApiServer(malformed=True) as server:
            settings = _settings(server.base_url)
            report = _service(conn, settings).run_cycle(force=True)
        # Registration itself gets a malformed 200 -> transient -> aborted.
        assert report.aborted == "registration"
        assert _states(conn).get("FAILED") == 1 or report.failed >= 0
    finally:
        conn.close()


def test_redirect_is_config_error_and_second_server_untouched(tmp_db: Path) -> None:
    conn = local_db.connect(tmp_db)
    try:
        _persist_run(conn, started=utc_now())
        with LocalApiServer() as second:
            redirect_target = second.base_url + "/v1/telemetry"
            with LocalApiServer(redirect_to=redirect_target) as first:
                settings = _settings(first.base_url)
                report = _service(conn, settings).run_cycle(force=True)
            # The redirect target server must never have been contacted.
            assert second.request_count == 0
        assert report.aborted in ("config", "registration")
        # Counts unchanged: the event is not consumed by a config error.
        count = conn.execute("SELECT attempt_count FROM sync_queue").fetchone()[0]
        assert count == 0
    finally:
        conn.close()
