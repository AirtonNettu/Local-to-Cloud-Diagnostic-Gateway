"""Memory collector (design B.6)."""

from __future__ import annotations

from dataclasses import dataclass

import psutil

__all__ = ["MemoryInfo", "collect_memory"]


@dataclass(frozen=True)
class MemoryInfo:
    """Virtual memory totals and current usage percent."""

    total_bytes: int
    available_bytes: int
    used_bytes: int
    percent: float


def collect_memory() -> MemoryInfo:
    """Collect virtual memory information from psutil."""
    vm = psutil.virtual_memory()
    return MemoryInfo(
        total_bytes=int(vm.total),
        available_bytes=int(vm.available),
        used_bytes=int(vm.used),
        percent=round(float(vm.percent), 1),
    )
