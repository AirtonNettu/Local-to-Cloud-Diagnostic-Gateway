"""Storage-failure behavior for the scan and status commands (design B.8)."""

from __future__ import annotations

import logging
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


@pytest.fixture
def stubbed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("LOCALAPPDATA", str(data_dir))
    monkeypatch.setattr(
        commands, "live_collector_set", lambda platform, settings: _collector_set()
    )
    monkeypatch.setattr(commands, "SystemProber", _FakeProber)
    return data_dir


def test_scan_storage_error_prints_report_exits_1_logs_event(
    stubbed: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # DATABASE_PATH points at a directory, so connect() raises StorageError.
    bad_db = stubbed / "a-directory.db"
    bad_db.mkdir(parents=True)
    monkeypatch.setenv("DATABASE_PATH", str(bad_db))

    with caplog.at_level(logging.ERROR, logger="agent.commands"):
        code = main(["scan"])

    assert code == 1
    out = capsys.readouterr().out
    assert "OVERALL HEALTH" in out  # the report was still printed
    events = [r for r in caplog.records if getattr(r, "event", None) == "storage_error"]
    assert events, "scan must log event=storage_error on a storage failure"


def test_scan_success_persists_and_exits_0(
    stubbed: Path, capsys: pytest.CaptureFixture
) -> None:
    assert main(["scan"]) == 0
    out = capsys.readouterr().out
    assert "OVERALL HEALTH" in out
    # A live run with sync disabled still writes the DB.
    assert (stubbed / "LocalToCloudDiagnosticGateway" / "agent.db").is_file()


def test_status_database_path_is_directory_exits_1(
    stubbed: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    bad_db = stubbed / "status-dir.db"
    bad_db.mkdir(parents=True)
    monkeypatch.setenv("DATABASE_PATH", str(bad_db))

    code = main(["status"])

    assert code == 1
    err = capsys.readouterr().err
    assert "local database unavailable" in err


def test_status_no_local_data_yet(
    stubbed: Path, capsys: pytest.CaptureFixture
) -> None:
    assert main(["status"]) == 0
    assert "no local data yet" in capsys.readouterr().out
