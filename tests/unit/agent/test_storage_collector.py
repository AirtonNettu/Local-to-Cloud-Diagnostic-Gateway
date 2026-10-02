"""Tests for the storage collector (skip remote/cdrom, PARTIAL on OSError)."""

from __future__ import annotations

from collections import namedtuple

import pytest

from agent.collectors import storage
from agent.collectors.base import PartialCollection

_Partition = namedtuple("_Partition", "device mountpoint fstype opts")
_Usage = namedtuple("_Usage", "total used free percent")


def _usage(percent: float) -> _Usage:
    total = 1000
    used = int(total * percent / 100)
    return _Usage(total=total, used=used, free=total - used, percent=percent)


def test_remote_and_cdrom_skipped_before_disk_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parts = [
        _Partition("C:\\", "C:\\", "NTFS", "rw,fixed"),
        _Partition("Z:\\", "Z:\\", "", "rw,remote"),
        _Partition("D:\\", "D:\\", "CDFS", "ro,cdrom"),
    ]
    called: list[str] = []

    def _disk_usage(mountpoint: str) -> _Usage:
        called.append(mountpoint)
        return _usage(30.0)

    monkeypatch.setattr(storage.psutil, "disk_partitions", lambda all: parts)
    monkeypatch.setattr(storage.psutil, "disk_usage", _disk_usage)

    volumes = storage.collect_storage()
    # Only the fixed volume is probed; remote/cdrom are skipped before usage.
    assert called == ["C:\\"]
    assert [v.mountpoint for v in volumes] == ["C:\\"]


def test_unreadable_volume_is_partial(monkeypatch: pytest.MonkeyPatch) -> None:
    parts = [
        _Partition("C:\\", "C:\\", "NTFS", "rw,fixed"),
        _Partition("G:\\", "G:\\", "", "rw,removable"),
    ]

    def _disk_usage(mountpoint: str) -> _Usage:
        if mountpoint == "G:\\":
            raise OSError("empty card reader")
        return _usage(50.0)

    monkeypatch.setattr(storage.psutil, "disk_partitions", lambda all: parts)
    monkeypatch.setattr(storage.psutil, "disk_usage", _disk_usage)

    with pytest.raises(PartialCollection) as exc:
        storage.collect_storage()
    partial = exc.value
    assert len(partial.data) == 1
    assert partial.data[0].mountpoint == "C:\\"
    assert any("G:\\" in e for e in partial.item_errors)


def test_run_collector_maps_partial(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent.collectors.base import CollectorStatus, run_collector

    parts = [_Partition("G:\\", "G:\\", "", "rw,removable")]
    monkeypatch.setattr(storage.psutil, "disk_partitions", lambda all: parts)
    monkeypatch.setattr(
        storage.psutil,
        "disk_usage",
        lambda m: (_ for _ in ()).throw(OSError("x")),
    )
    result = run_collector("storage", storage.collect_storage)
    assert result.status is CollectorStatus.PARTIAL
    assert result.data == []
