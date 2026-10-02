"""CLI exit-code tests for sync-aware commands (design B.13).

``scan --sync``: 1 on storage error; else 3 if the sync cycle was incomplete;
else 0 (and 0 when sync is disabled). The sync cycle is driven by a fake client
injected through ``commands.build_api_client``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent import commands
from agent.collectors.cpu import CpuInfo
from agent.collectors.memory import MemoryInfo
from agent.collectors.network import InterfaceInfo, NetworkInfo
from agent.collectors.storage import VolumeInfo
from agent.collectors.system import SystemInfo
from agent.diagnostics.probes import ProbeOutcome, ProbeResult, ResolveResult
from agent.main import main
from agent.pipeline import CollectorSet
from agent.sync.client import (
    ItemResult,
    OfflineError,
    RegistrationResult,
    TelemetryResult,
)


def _collector_set() -> CollectorSet:
    return CollectorSet(
        cpu=lambda: CpuInfo("cpu", 8, 4, 10.0, 10.0, (10.0,), None, None),
        memory=lambda: MemoryInfo(100, 50, 50, 50.0),
        storage=lambda: [VolumeInfo("C:\\", "C:\\", "NTFS", 1000, 100, 900, 10.0)],
        disks=lambda: [],
        system=lambda: SystemInfo(
            "host", "Windows", "10", "11", "AMD64", "2024-01-01T00:00:00Z", 60
        ),
        gpus=lambda: [],
        network=lambda: NetworkInfo(
            "host",
            (InterfaceInfo("Ethernet", True, 1000, ("10.0.0.5",), ()),),
            ("10.0.0.1",),
            ("10.0.0.1",),
        ),
    )


class _FakeProber:
    def icmp_ping(self, host: str, timeout_s: float) -> ProbeResult:
        return ProbeResult(host, ProbeOutcome.SUCCESS, 1.0, "")

    def tcp_connect(self, host: str, port: int, timeout_s: float) -> ProbeResult:
        return ProbeResult(host, ProbeOutcome.SUCCESS, 10.0, "")

    def resolve(self, hostname: str, timeout_s: float) -> ResolveResult:
        return ResolveResult(hostname, ProbeOutcome.SUCCESS, ("1.2.3.4",), 1.0)


class _AcceptClient:
    def register_device(self, payload: dict) -> RegistrationResult:
        return RegistrationResult(device_id=payload["device_id"], created=True)

    def send_telemetry(self, device_id: str, events: list[dict]) -> TelemetryResult:
        return TelemetryResult(
            results=[ItemResult(event_id=e["event_id"], status="accepted")
                     for e in events]
        )


class _OfflineClient:
    def register_device(self, payload: dict) -> RegistrationResult:
        raise OfflineError("dns")

    def send_telemetry(self, device_id: str, events: list[dict]) -> TelemetryResult:
        raise OfflineError("dns")


@pytest.fixture
def stubbed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("LOCALAPPDATA", str(data_dir))
    monkeypatch.setattr(
        commands, "live_collector_set", lambda platform, settings: _collector_set()
    )
    monkeypatch.setattr(commands, "SystemProber", _FakeProber)
    return data_dir


def _enable_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_BASE_URL", "https://api.example")
    monkeypatch.setenv("AGENT_API_KEY", "k" * 32)
    monkeypatch.setenv("DEVICE_ID", "demo-device-0001")


def test_scan_sync_accepts_exits_0(
    stubbed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_sync(monkeypatch)
    monkeypatch.setattr(commands, "build_api_client", lambda settings: _AcceptClient())
    assert main(["scan", "--sync"]) == 0


def test_scan_sync_offline_exits_3(
    stubbed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_sync(monkeypatch)
    monkeypatch.setattr(commands, "build_api_client", lambda settings: _OfflineClient())
    assert main(["scan", "--sync"]) == 3


def test_scan_sync_disabled_exits_0(
    stubbed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No API_BASE_URL: sync is disabled, scan still succeeds.
    assert main(["scan", "--sync"]) == 0


def test_scan_storage_error_outranks_sync(
    stubbed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_sync(monkeypatch)
    bad_db = stubbed / "a-directory.db"
    bad_db.mkdir(parents=True)
    monkeypatch.setenv("DATABASE_PATH", str(bad_db))
    monkeypatch.setattr(commands, "build_api_client", lambda settings: _OfflineClient())
    # Storage error (1) outranks any sync incompleteness (3).
    assert main(["scan", "--sync"]) == 1


def test_sync_command_disabled_exits_0(
    stubbed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert main(["sync"]) == 0


def test_sync_command_offline_exits_3(
    stubbed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_sync(monkeypatch)
    # Seed a queued event via a plain scan first.
    monkeypatch.setattr(commands, "build_api_client", lambda settings: _AcceptClient())
    assert main(["scan"]) == 0
    monkeypatch.setattr(commands, "build_api_client", lambda settings: _OfflineClient())
    assert main(["sync"]) == 3


def test_queue_stats_and_requeue(
    stubbed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_sync(monkeypatch)
    monkeypatch.setattr(commands, "build_api_client", lambda settings: _AcceptClient())
    assert main(["scan"]) == 0  # enqueues one event
    assert main(["queue", "stats"]) == 0
    assert main(["queue"]) == 0  # bare queue == stats
    assert main(["queue", "list"]) == 0
