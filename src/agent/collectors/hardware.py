"""Hardware collectors: GPU and physical disk health, plus an aggregate view.

``GpuInfo`` and ``PhysicalDiskInfo`` are defined in ``platform_support/base.py``
and re-exported here to avoid an import cycle. ``collect_hardware_view``
aggregates every hardware-related collector for the ``hardware`` command.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent.collectors.base import CollectorResult, run_collector
from agent.collectors.cpu import CpuInfo, collect_cpu
from agent.collectors.memory import MemoryInfo, collect_memory
from agent.collectors.storage import VolumeInfo, collect_storage
from agent.collectors.system import SystemInfo, collect_system
from agent.platform_support.base import GpuInfo, PhysicalDiskInfo, PlatformInfo

__all__ = [
    "GpuInfo",
    "PhysicalDiskInfo",
    "collect_gpus",
    "collect_physical_disks",
    "HardwareView",
    "collect_hardware_view",
]


def collect_gpus(platform_info: PlatformInfo) -> list[GpuInfo]:
    """Collect installed graphics adapters (raises on platform failure)."""
    return platform_info.gpus()


def collect_physical_disks(platform_info: PlatformInfo) -> list[PhysicalDiskInfo]:
    """Collect physical disk health (raises on platform failure)."""
    return platform_info.physical_disks()


@dataclass(frozen=True)
class HardwareView:
    """Aggregated hardware collector results for the ``hardware`` command."""

    cpu: CollectorResult[CpuInfo]
    memory: CollectorResult[MemoryInfo]
    storage: CollectorResult[list[VolumeInfo]]
    system: CollectorResult[SystemInfo]
    gpus: CollectorResult[list[GpuInfo]]
    disks: CollectorResult[list[PhysicalDiskInfo]]


def collect_hardware_view(
    platform_info: PlatformInfo,
    *,
    cpu_sample_count: int,
    cpu_sample_interval_seconds: float,
) -> HardwareView:
    """Run every hardware collector through the isolation boundary."""
    return HardwareView(
        cpu=run_collector(
            "cpu",
            lambda: collect_cpu(
                platform_info,
                sample_count=cpu_sample_count,
                sample_interval_seconds=cpu_sample_interval_seconds,
            ),
        ),
        memory=run_collector("memory", collect_memory),
        storage=run_collector("storage", collect_storage),
        system=run_collector("system", collect_system),
        gpus=run_collector("gpus", lambda: collect_gpus(platform_info)),
        disks=run_collector("disks", lambda: collect_physical_disks(platform_info)),
    )
