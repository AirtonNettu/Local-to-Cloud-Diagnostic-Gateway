"""Platform support package: ``get_platform()`` selects the OS implementation."""

from __future__ import annotations

import sys

from agent.platform_support.base import (
    GpuInfo,
    PhysicalDiskInfo,
    PlatformInfo,
    PlatformQueryError,
    PlatformUnavailableError,
)
from agent.platform_support.windows import UnsupportedPlatform, WindowsPlatform

__all__ = [
    "GpuInfo",
    "PhysicalDiskInfo",
    "PlatformInfo",
    "PlatformQueryError",
    "PlatformUnavailableError",
    "WindowsPlatform",
    "UnsupportedPlatform",
    "get_platform",
]


def get_platform() -> PlatformInfo:
    """Return ``WindowsPlatform`` on Windows, else ``UnsupportedPlatform``."""
    if sys.platform == "win32":
        return WindowsPlatform()
    return UnsupportedPlatform()
