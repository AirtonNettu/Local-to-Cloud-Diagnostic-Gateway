"""Secret-leak test (design B.20): a sentinel key must never reach a log.

A full sync cycle runs with a sentinel API key against an unreachable endpoint
while every logger is captured and the agent log file is inspected. The sentinel
value must appear in no captured log record and no log file, proving the
``Secret`` wrapper and the logging redaction filter keep the key out of logs.
"""

from __future__ import annotations

import logging
import random
import sqlite3
from pathlib import Path

import pytest

from agent.config.settings import Secret, Settings, load_settings
from agent.storage import local_db
from agent.storage.local_db import LocalStore
from agent.sync.client import ApiClient, ConnectivityError, HttpResponse
from agent.sync.service import SyncService
from shared.models.diagnostic import (
    DiagnosticResult,
    HealthStatus,
    NetworkStatus,
    RunSource,
)
from shared.utils.ids import new_uuid7
from shared.utils.timeutil import to_iso, utc_now

SENTINEL_KEY = "SENTINEL-KEY-" + "Z" * 32
DEVICE_ID = "leak-device-0001"


class _SentinelTransport:
    """Raises after being handed the sentinel key, so a leak would be loud."""

    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        # The real Authorization header carries the key; prove it is never logged.
        raise ConnectivityError("simulated unreachable")


def _settings() -> Settings:
    return load_settings(
        env={
            "API_BASE_URL": "https://unreachable.invalid",
            "AGENT_API_KEY": SENTINEL_KEY,
            "DEVICE_ID": DEVICE_ID,
        }
    )


def _persist_run(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT INTO devices (device_id, device_name, hostname, is_local, created_at)
        VALUES (?, 'Leak PC', 'LEAK-PC', 0, ?)
        """,
        (DEVICE_ID, to_iso(utc_now())),
    )
    conn.commit()
    result = DiagnosticResult(
        run_id=new_uuid7(),
        device_id=DEVICE_ID,
        started_at=to_iso(utc_now()),
        finished_at=to_iso(utc_now()),
        source=RunSource.LIVE,
        status=HealthStatus.HEALTHY,
        network_status=NetworkStatus.HEALTHY,
        checks=(),
        alerts=(),
        metrics=(),
        facts={
            "cpu": {"model": "Leak CPU", "logical_cpus": 4, "physical_cores": 4},
            "memory": {"total_bytes": 16 * 1024**3},
            "system": {
                "os_name": "Windows",
                "os_version": "10.0.22631",
                "architecture": "AMD64",
                "hostname": "LEAK-PC",
            },
        },
    )
    LocalStore(conn).save_run(result, enqueue_event=True)


def test_sentinel_key_never_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    log_file = tmp_path / "agent.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    root = logging.getLogger()
    root.addHandler(file_handler)
    previous_level = root.level
    root.setLevel(logging.DEBUG)

    db_path = tmp_path / "agent.db"
    conn = local_db.connect(db_path)
    try:
        _persist_run(conn)
        settings = _settings()
        client = ApiClient(
            base_url=settings.api_base_url,
            api_key=Secret(SENTINEL_KEY),
            transport=_SentinelTransport(),
            timeout=5,
        )
        service = SyncService(
            conn, settings, client, device_id=DEVICE_ID, rng=random.Random(0)
        )
        with caplog.at_level(logging.DEBUG):
            service.run_cycle(force=True)
    finally:
        conn.close()
        root.removeHandler(file_handler)
        file_handler.close()
        root.setLevel(previous_level)

    # No captured log record carries the sentinel.
    for record in caplog.records:
        assert SENTINEL_KEY not in record.getMessage()
        for value in record.__dict__.values():
            assert SENTINEL_KEY not in str(value)

    # No log file content carries the sentinel.
    assert SENTINEL_KEY not in log_file.read_text(encoding="utf-8")
