"""System collector: hostname, OS, architecture, boot time, uptime (design B.6)."""

from __future__ import annotations

import platform
import socket
from collections.abc import Callable
from dataclasses import dataclass

import psutil

__all__ = ["SystemInfo", "collect_system"]


@dataclass(frozen=True)
class SystemInfo:
    """Operating system identity and uptime."""

    hostname: str
    os_name: str
    os_version: str
    os_release: str
    architecture: str
    boot_time: str
    uptime_seconds: int


def collect_system(now: Callable[[], float] | None = None) -> SystemInfo:
    """Collect OS and uptime information.

    ``now`` returns the current epoch seconds (injected for deterministic tests;
    defaults to ``time.time``).
    """
    import time

    current = (now or time.time)()
    boot = float(psutil.boot_time())
    uptime = max(0, int(current - boot))

    from datetime import UTC, datetime

    boot_iso = datetime.fromtimestamp(boot, tz=UTC).isoformat().replace("+00:00", "Z")

    architecture = platform.machine() or "unknown"
    return SystemInfo(
        hostname=socket.gethostname() or "unknown",
        os_name=platform.system() or "unknown",
        os_version=platform.version() or "unknown",
        os_release=platform.release() or "unknown",
        architecture=architecture,
        boot_time=boot_iso,
        uptime_seconds=uptime,
    )
