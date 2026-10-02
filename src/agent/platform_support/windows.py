"""Windows platform queries (read-only CIM/Storage, locale-independent).

Every query is a module-level constant PowerShell script run through
``run_powershell_json``. Enum-valued fields can arrive as strings or as integers
(PowerShell 5.1 ``ConvertTo-Json`` serializes some enums numerically), so numeric
values are mapped via lookup tables; strings are kept verbatim. ``bool`` is
rejected because it is an ``int`` subclass.

``SerialNumber`` and ``UniqueId`` are never selected: physical disks are
identified by position, never by a hardware fingerprint (privacy, design B.6).
"""

from __future__ import annotations

import ipaddress
from typing import Any

from agent.platform_support.base import (
    GpuInfo,
    PhysicalDiskInfo,
    PlatformQueryError,
    PlatformUnavailableError,
)
from agent.platform_support.powershell import run_powershell_json

__all__ = ["WindowsPlatform", "UnsupportedPlatform"]

# uint32 AdapterRAM saturates at 4 GiB and is unreliable at or above that.
_ADAPTER_RAM_SATURATION = 4294967295

_HEALTH_STATUS = {0: "Healthy", 1: "Warning", 2: "Unhealthy", 5: "Unknown"}
_MEDIA_TYPE = {0: "Unspecified", 3: "HDD", 4: "SSD", 5: "SCM"}
_BUS_TYPE = {
    1: "SCSI",
    3: "ATA",
    7: "USB",
    8: "RAID",
    10: "SAS",
    11: "SATA",
    12: "SD",
    13: "MMC",
    17: "NVMe",
}
_OPERATIONAL_STATUS = {
    2: "OK",
    3: "Degraded",
    0xD010: "Online",
    0xD012: "No Media",
    0xD013: "Not Ready",
}

_GPU_SCRIPT = (
    "Get-CimInstance Win32_VideoController | "
    "Select-Object Name, DriverVersion, AdapterRAM | "
    "ConvertTo-Json -Compress -Depth 3"
)
_NETWORK_SCRIPT = (
    "Get-CimInstance Win32_NetworkAdapterConfiguration "
    '-Filter "IPEnabled=TRUE" | '
    "Select-Object DefaultIPGateway, DNSServerSearchOrder | "
    "ConvertTo-Json -Compress -Depth 3"
)
_CPU_SCRIPT = (
    "Get-CimInstance Win32_Processor | Select-Object -First 1 Name | "
    "ConvertTo-Json -Compress -Depth 3"
)
_DISKS_SCRIPT = (
    "Get-PhysicalDisk | Select-Object FriendlyName, MediaType, BusType, "
    "HealthStatus, OperationalStatus, Size | "
    "ConvertTo-Json -Compress -Depth 3"
)


def _as_list(value: Any) -> list[Any]:
    """Normalize a scalar / ``None`` / list into a list (never iterate a str)."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _is_int(value: Any) -> bool:
    """True for a real ``int`` (``bool`` is rejected: it subclasses ``int``)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _map_enum(value: Any, table: dict[int, str], unknown: str = "Unknown") -> str:
    """Map one enum field: keep strings, look up ints, else ``unknown``."""
    if isinstance(value, str):
        return value
    if _is_int(value):
        return table.get(value, unknown)
    return unknown


def _map_operational_status(value: Any) -> str:
    """Normalize OperationalStatus (scalar/array of str or int) to a string."""
    items = _as_list(value)
    mapped: list[str] = []
    for item in items:
        if isinstance(item, str):
            mapped.append(item)
        elif _is_int(item):
            mapped.append(_OPERATIONAL_STATUS.get(item, str(item)))
    if not mapped:
        return "Unknown"
    return ", ".join(mapped)


def _normalize_ips(value: Any) -> list[str]:
    """Validate, de-duplicate and sort IPs (IPv4 first) from a CIM array."""
    seen: list[str] = []
    for item in _as_list(value):
        if not isinstance(item, str):
            continue
        candidate = item.strip()
        if not candidate:
            continue
        try:
            parsed = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        text = str(parsed)
        if text not in seen:
            seen.append(text)
    seen.sort(key=lambda ip: (ipaddress.ip_address(ip).version, ip))
    return seen


class WindowsPlatform:
    """Read-only Windows platform queries (design B.6)."""

    def cpu_name(self) -> str:
        rows = run_powershell_json(_CPU_SCRIPT)
        for row in rows:
            name = row.get("Name") if isinstance(row, dict) else None
            if isinstance(name, str) and name.strip():
                return " ".join(name.split())
        raise PlatformQueryError("CPU name not reported")

    def gpus(self) -> list[GpuInfo]:
        rows = run_powershell_json(_GPU_SCRIPT)
        gpus: list[GpuInfo] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = row.get("Name")
            if not isinstance(name, str) or not name.strip():
                continue
            driver = row.get("DriverVersion")
            driver_version = (
                driver.strip() if isinstance(driver, str) and driver.strip() else None
            )
            gpus.append(
                GpuInfo(
                    name=name.strip(),
                    driver_version=driver_version,
                    adapter_ram_bytes=_gpu_ram(row.get("AdapterRAM")),
                )
            )
        return gpus

    def network_config(self) -> tuple[list[str], list[str]]:
        rows = run_powershell_json(_NETWORK_SCRIPT)
        gateways: list[str] = []
        dns_servers: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            for ip in _normalize_ips(row.get("DefaultIPGateway")):
                if ip not in gateways:
                    gateways.append(ip)
            for ip in _normalize_ips(row.get("DNSServerSearchOrder")):
                if ip not in dns_servers:
                    dns_servers.append(ip)
        gateways.sort(key=lambda ip: (ipaddress.ip_address(ip).version, ip))
        return gateways, dns_servers

    def physical_disks(self) -> list[PhysicalDiskInfo]:
        rows = run_powershell_json(_DISKS_SCRIPT)
        disks: list[PhysicalDiskInfo] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            friendly = row.get("FriendlyName")
            disks.append(
                PhysicalDiskInfo(
                    friendly_name=(
                        friendly.strip()
                        if isinstance(friendly, str) and friendly.strip()
                        else "unknown"
                    ),
                    media_type=_map_enum(row.get("MediaType"), _MEDIA_TYPE),
                    bus_type=_map_enum(row.get("BusType"), _BUS_TYPE),
                    health_status=_map_enum(row.get("HealthStatus"), _HEALTH_STATUS),
                    operational_status=_map_operational_status(
                        row.get("OperationalStatus")
                    ),
                    size_bytes=_disk_size(row.get("Size")),
                )
            )
        return disks


def _gpu_ram(value: Any) -> int | None:
    """AdapterRAM is uint32; saturated or non-positive values are unreliable."""
    if not _is_int(value):
        return None
    ram = int(value)
    if ram <= 0 or ram >= _ADAPTER_RAM_SATURATION:
        return None
    return ram


def _disk_size(value: Any) -> int | None:
    if _is_int(value):
        size = int(value)
        return size if size > 0 else None
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


class UnsupportedPlatform:
    """Non-Windows placeholder: every query is unavailable (design B.6)."""

    def cpu_name(self) -> str:
        raise PlatformUnavailableError("platform queries require Windows")

    def gpus(self) -> list[GpuInfo]:
        raise PlatformUnavailableError("platform queries require Windows")

    def network_config(self) -> tuple[list[str], list[str]]:
        raise PlatformUnavailableError("platform queries require Windows")

    def physical_disks(self) -> list[PhysicalDiskInfo]:
        raise PlatformUnavailableError("platform queries require Windows")
