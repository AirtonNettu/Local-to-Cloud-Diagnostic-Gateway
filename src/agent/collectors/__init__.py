"""Collectors package: CPU, memory, storage, system, network and hardware."""

from __future__ import annotations

from agent.collectors.base import (
    CollectorResult,
    CollectorStatus,
    PartialCollection,
    run_collector,
)

__all__ = [
    "CollectorResult",
    "CollectorStatus",
    "PartialCollection",
    "run_collector",
]
