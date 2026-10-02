"""`run` loop tests: interruptible sleep and the exit precedence (NIT8)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent import commands
from agent.collectors.cpu import CpuInfo
from agent.collectors.memory import MemoryInfo
from agent.collectors.network import InterfaceInfo, NetworkInfo
from agent.collectors.storage import VolumeInfo
from agent.collectors.system import SystemInfo
from agent.commands import _sleep_interruptibly, _worse_exit
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


# --- _sleep_interruptibly ----------------------------------------------------
def test_sleep_slices_at_most_one_second() -> None:
    slices: list[float] = []
    ticks = iter([0.0, 0.0, 1.0, 2.0, 3.0, 10.0])

    def fake_monotonic() -> float:
        return next(ticks)

    _sleep_interruptibly(
        3.0, sleep=slices.append, monotonic=fake_monotonic
    )
    assert slices  # it did sleep
    assert all(s <= 1.0 for s in slices)


def test_sleep_zero_returns_immediately() -> None:
    called: list[float] = []
    _sleep_interruptibly(0.0, sleep=called.append, monotonic=lambda: 0.0)
    assert called == []


def test_sleep_propagates_keyboard_interrupt() -> None:
    def boom(_seconds: float) -> None:
        raise KeyboardInterrupt

    ticks = iter([0.0, 0.0, 0.0, 0.0])
    with pytest.raises(KeyboardInterrupt):
        _sleep_interruptibly(5.0, sleep=boom, monotonic=lambda: next(ticks))


# --- exit precedence ---------------------------------------------------------
def test_worse_exit_precedence() -> None:
    assert _worse_exit(0, 3) == 3
    assert _worse_exit(3, 1) == 1
    assert _worse_exit(1, 3) == 1  # 1 outranks 3
    assert _worse_exit(0, 0) == 0


def test_run_iterations_all_ok_exits_0(
    stubbed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("API_BASE_URL", "https://api.example")
    monkeypatch.setenv("AGENT_API_KEY", "k" * 32)
    monkeypatch.setenv("DEVICE_ID", "demo-device-0001")
    monkeypatch.setattr(commands, "build_api_client", lambda settings: _AcceptClient())
    monkeypatch.setattr(commands, "_sleep_interruptibly", lambda *a, **k: None)
    assert main(["run", "--iterations", "2"]) == 0


def test_run_iterations_offline_exits_3(
    stubbed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("API_BASE_URL", "https://api.example")
    monkeypatch.setenv("AGENT_API_KEY", "k" * 32)
    monkeypatch.setenv("DEVICE_ID", "demo-device-0001")
    monkeypatch.setattr(commands, "build_api_client", lambda settings: _OfflineClient())
    monkeypatch.setattr(commands, "_sleep_interruptibly", lambda *a, **k: None)
    assert main(["run", "--iterations", "2"]) == 3


def test_run_iterations_storage_error_exits_1(
    stubbed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("API_BASE_URL", "https://api.example")
    monkeypatch.setenv("AGENT_API_KEY", "k" * 32)
    monkeypatch.setenv("DEVICE_ID", "demo-device-0001")
    bad_db = stubbed / "a-directory.db"
    bad_db.mkdir(parents=True)
    monkeypatch.setenv("DATABASE_PATH", str(bad_db))
    monkeypatch.setattr(commands, "build_api_client", lambda settings: _OfflineClient())
    monkeypatch.setattr(commands, "_sleep_interruptibly", lambda *a, **k: None)
    # Storage error (1) outranks sync incomplete (3) across iterations.
    assert main(["run", "--iterations", "2"]) == 1
