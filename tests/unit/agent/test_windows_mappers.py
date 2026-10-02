"""Tests for the Windows platform enum mappers and PowerShell gateway."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.platform_support import windows
from agent.platform_support.base import PlatformQueryError, PlatformUnavailableError
from agent.platform_support.powershell import run_powershell_json

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "powershell"


def _parse_disks(rows: list[dict]) -> list:
    """Reproduce WindowsPlatform.physical_disks over fixture rows."""
    platform = windows.WindowsPlatform()
    # Monkeypatch-free: call the private mappers directly via a fake row loop.
    disks = []
    for row in rows:
        disks.append(
            (
                row["FriendlyName"],
                windows._map_enum(row.get("MediaType"), windows._MEDIA_TYPE),
                windows._map_enum(row.get("BusType"), windows._BUS_TYPE),
                windows._map_enum(row.get("HealthStatus"), windows._HEALTH_STATUS),
                windows._map_operational_status(row.get("OperationalStatus")),
            )
        )
    assert platform is not None
    return disks


def test_string_and_numeric_fixtures_map_equal() -> None:
    strings = json.loads((_FIXTURES / "physical_disks_strings.json").read_text("utf-8"))
    numeric = json.loads((_FIXTURES / "physical_disks_numeric.json").read_text("utf-8"))
    assert _parse_disks(strings) == _parse_disks(numeric)


def test_health_status_mapping() -> None:
    assert windows._map_enum(0, windows._HEALTH_STATUS) == "Healthy"
    assert windows._map_enum(1, windows._HEALTH_STATUS) == "Warning"
    assert windows._map_enum(2, windows._HEALTH_STATUS) == "Unhealthy"
    assert windows._map_enum(5, windows._HEALTH_STATUS) == "Unknown"
    assert windows._map_enum(99, windows._HEALTH_STATUS) == "Unknown"


def test_media_and_bus_mapping() -> None:
    assert windows._map_enum(4, windows._MEDIA_TYPE) == "SSD"
    assert windows._map_enum(3, windows._MEDIA_TYPE) == "HDD"
    assert windows._map_enum(17, windows._BUS_TYPE) == "NVMe"
    assert windows._map_enum(11, windows._BUS_TYPE) == "SATA"


def test_bool_is_rejected_as_unmapped() -> None:
    # bool is an int subclass; it must not map through the int tables.
    assert windows._map_enum(True, windows._HEALTH_STATUS) == "Unknown"
    assert windows._map_enum(False, windows._MEDIA_TYPE) == "Unknown"


def test_strings_kept_verbatim() -> None:
    assert windows._map_enum("SSD", windows._MEDIA_TYPE) == "SSD"
    assert windows._map_enum("CustomValue", windows._HEALTH_STATUS) == "CustomValue"


def test_operational_status_scalar_string() -> None:
    assert windows._map_operational_status("OK") == "OK"


def test_operational_status_array_mixed() -> None:
    assert windows._map_operational_status([2, "Spare"]) == "OK, Spare"


def test_operational_status_empty_is_unknown() -> None:
    assert windows._map_operational_status(None) == "Unknown"
    assert windows._map_operational_status([]) == "Unknown"


def test_operational_status_unmapped_int_is_numeric_string() -> None:
    assert windows._map_operational_status(777) == "777"


def test_as_list_never_iterates_a_string() -> None:
    assert windows._as_list("OK") == ["OK"]
    assert windows._as_list(None) == []
    assert windows._as_list([1, 2]) == [1, 2]


def test_normalize_ips_dedup_and_order() -> None:
    ips = windows._normalize_ips(["8.8.8.8", "8.8.8.8", "2001:db8::1", "bad"])
    assert ips == ["8.8.8.8", "2001:db8::1"]


def test_run_powershell_json_filenotfound(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*args: object, **kwargs: object) -> object:
        raise FileNotFoundError("no powershell")

    monkeypatch.setattr("agent.platform_support.powershell.subprocess.run", _raise)
    with pytest.raises(PlatformUnavailableError):
        run_powershell_json("x | ConvertTo-Json")


def test_run_powershell_json_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Completed:
        returncode = 1
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(
        "agent.platform_support.powershell.subprocess.run",
        lambda *a, **k: _Completed(),
    )
    with pytest.raises(PlatformQueryError):
        run_powershell_json("x | ConvertTo-Json")


def test_run_powershell_json_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Completed:
        returncode = 0
        stdout = "not json"
        stderr = ""

    monkeypatch.setattr(
        "agent.platform_support.powershell.subprocess.run",
        lambda *a, **k: _Completed(),
    )
    with pytest.raises(PlatformQueryError):
        run_powershell_json("x | ConvertTo-Json")


def test_run_powershell_json_single_object_to_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Completed:
        returncode = 0
        stdout = '{"Name": "cpu"}'
        stderr = ""

    monkeypatch.setattr(
        "agent.platform_support.powershell.subprocess.run",
        lambda *a, **k: _Completed(),
    )
    assert run_powershell_json("x | ConvertTo-Json") == [{"Name": "cpu"}]


def test_unsupported_platform_raises_unavailable() -> None:
    unsupported = windows.UnsupportedPlatform()
    with pytest.raises(PlatformUnavailableError):
        unsupported.cpu_name()
    with pytest.raises(PlatformUnavailableError):
        unsupported.gpus()
    with pytest.raises(PlatformUnavailableError):
        unsupported.network_config()
    with pytest.raises(PlatformUnavailableError):
        unsupported.physical_disks()
