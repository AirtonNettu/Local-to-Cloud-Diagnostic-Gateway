"""Platform abstraction: the single read-only OS-specific query surface.

The agent isolates every Windows-specific query (GPU, gateway/DNS, physical
disk health) behind the :class:`PlatformInfo` protocol so the rest of the code
is portable and unit-testable without real hardware. Implementations never
mutate the system and surface failures through two exceptions only:

- :class:`PlatformUnavailableError` — the tool or OS feature is missing (for
  example PowerShell is absent or the OS is not Windows). Collectors treat this
  as "unavailable" (``None`` fields / ``UNAVAILABLE`` status), logged at DEBUG.
- :class:`PlatformQueryError` — a query ran but failed (timeout, non-zero exit,
  invalid output). Collectors treat this as a failure/partial result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = [
    "PlatformUnavailableError",
    "PlatformQueryError",
    "GpuInfo",
    "PhysicalDiskInfo",
    "PlatformInfo",
]


class PlatformUnavailableError(Exception):
    """The platform tool or OS feature is not available (e.g. not Windows)."""


class PlatformQueryError(Exception):
    """A platform query executed but failed (timeout, bad exit, bad output)."""


@dataclass(frozen=True)
class GpuInfo:
    """A graphics adapter as reported by the platform (best effort)."""

    name: str
    driver_version: str | None
    adapter_ram_bytes: int | None


@dataclass(frozen=True)
class PhysicalDiskInfo:
    """Physical disk health details.

    ``friendly_name`` is a model string and is treated as sensitive: it stays in
    local facts/report only and never reaches checks, alerts, metrics or the
    cloud payload (design B.7).
    """

    friendly_name: str
    media_type: str
    bus_type: str
    health_status: str
    operational_status: str
    size_bytes: int | None


@runtime_checkable
class PlatformInfo(Protocol):
    """Read-only platform query surface (design B.6)."""

    def cpu_name(self) -> str:
        """Return the CPU marketing name (stripped). Raises on failure."""
        ...

    def gpus(self) -> list[GpuInfo]:
        """Return the installed graphics adapters. Raises on failure."""
        ...

    def network_config(self) -> tuple[list[str], list[str]]:
        """Return ``(gateways, dns_servers)``. Raises on failure."""
        ...

    def physical_disks(self) -> list[PhysicalDiskInfo]:
        """Return physical disk health details. Raises on failure."""
        ...
