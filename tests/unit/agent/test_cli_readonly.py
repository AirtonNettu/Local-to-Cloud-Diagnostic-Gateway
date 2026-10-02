"""Read-only commands create no database on a fresh data dir (design B.5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent import commands
from agent.collectors.base import CollectorResult, CollectorStatus
from agent.collectors.cpu import CpuInfo
from agent.collectors.memory import MemoryInfo
from agent.collectors.network import InterfaceInfo, NetworkInfo
from agent.collectors.storage import VolumeInfo
from agent.collectors.system import SystemInfo
from agent.diagnostics.engine import Collected
from agent.diagnostics.probes import ProbeOutcome, ProbeResult, ResolveResult
from agent.main import main


def _collected() -> Collected:
    def ok(data: object) -> CollectorResult:
        return CollectorResult("x", CollectorStatus.OK, data, (), 1)

    def unavailable() -> CollectorResult:
        return CollectorResult("x", CollectorStatus.UNAVAILABLE, None, (), 1)

    return Collected(
        cpu=ok(CpuInfo("cpu", 8, 4, 10.0, 10.0, (10.0,), None, None)),
        memory=ok(MemoryInfo(100, 50, 50, 50.0)),
        storage=ok([VolumeInfo("C:\\", "C:\\", "NTFS", 1000, 100, 900, 10.0)]),
        system=ok(
            SystemInfo(
                "host", "Windows", "10", "11", "AMD64", "2024-01-01T00:00:00Z", 60
            )
        ),
        gpus=unavailable(),
        disks=unavailable(),
        network=ok(
            NetworkInfo(
                "host",
                (InterfaceInfo("Ethernet", True, 1000, ("10.0.0.5",), ()),),
                ("10.0.0.1",),
                ("10.0.0.1",),
            )
        ),
    )


class _FakeProber:
    def icmp_ping(self, host: str, timeout_s: float) -> ProbeResult:
        return ProbeResult(host, ProbeOutcome.SUCCESS, 1.0, "")

    def tcp_connect(self, host: str, port: int, timeout_s: float) -> ProbeResult:
        return ProbeResult(host, ProbeOutcome.SUCCESS, 10.0, "")

    def resolve(self, hostname: str, timeout_s: float) -> ResolveResult:
        return ResolveResult(hostname, ProbeOutcome.SUCCESS, ("1.2.3.4",), 1.0)


@pytest.fixture
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the data dir at a fresh tmp dir and stub hardware/network."""
    data_dir = tmp_path / "data"
    monkeypatch.setenv("LOCALAPPDATA", str(data_dir))

    def _fake_collect(platform: object, settings: object) -> Collected:
        return _collected()

    monkeypatch.setattr(commands, "collect_all", _fake_collect)
    monkeypatch.setattr(commands, "SystemProber", _FakeProber)
    monkeypatch.setattr("agent.diagnostics.engine.collect_all", _fake_collect)
    return data_dir


def _no_db_files(data_dir: Path) -> bool:
    if not data_dir.exists():
        return True
    return not any(data_dir.rglob("*.db"))


def test_hardware_creates_no_db(isolated: Path, capsys: pytest.CaptureFixture) -> None:
    assert main(["hardware"]) == 0
    assert _no_db_files(isolated)
    assert "HARDWARE" in capsys.readouterr().out


def test_network_creates_no_db(isolated: Path, capsys: pytest.CaptureFixture) -> None:
    assert main(["network"]) == 0
    assert _no_db_files(isolated)
    out = capsys.readouterr().out
    assert "Classification" in out


def test_health_creates_no_db(isolated: Path, capsys: pytest.CaptureFixture) -> None:
    assert main(["health"]) == 0
    assert _no_db_files(isolated)
    out = capsys.readouterr().out
    assert "OVERALL HEALTH" in out


def test_health_device_not_yet_assigned(
    isolated: Path, capsys: pytest.CaptureFixture
) -> None:
    assert main(["health"]) == 0
    assert "not yet assigned" in capsys.readouterr().out


def test_hardware_json(isolated: Path, capsys: pytest.CaptureFixture) -> None:
    assert main(["hardware", "--json"]) == 0
    import json

    data = json.loads(capsys.readouterr().out)
    assert "cpu" in data
