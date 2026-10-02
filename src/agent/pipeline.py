"""Diagnostic pipeline: collect -> diagnose -> evaluate -> persist (+ enqueue).

``DiagnosticPipeline`` wires injected collectors, a prober, a health evaluator
and a clock, so demo mode and tests can substitute simulated providers without
any branching in production code (design B.8). ``run`` builds a
``DiagnosticResult``; when a ``store`` is given it persists the run (and
enqueues a sync event when ``enqueue`` is True) in one transaction.

A run without an identity can never be persisted; that precondition is checked
with an explicit ``ValueError`` (not a bare ``assert`` that ``-O`` would strip).
Metrics are built from facts and any ``None``-valued metric is omitted, never
emitted as null/NaN (review NIT13).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from agent.collectors.base import run_collector
from agent.collectors.cpu import CpuInfo, collect_cpu
from agent.collectors.hardware import (
    GpuInfo,
    PhysicalDiskInfo,
    collect_gpus,
    collect_physical_disks,
)
from agent.collectors.memory import MemoryInfo, collect_memory
from agent.collectors.network import NetworkInfo, collect_network
from agent.collectors.storage import VolumeInfo, collect_storage
from agent.collectors.system import SystemInfo, collect_system
from agent.config.settings import Settings
from agent.diagnostics.engine import Collected, evaluate_result
from agent.diagnostics.health import HealthEvaluator
from agent.diagnostics.network_diagnostics import NetworkDiagnostics
from agent.diagnostics.probes import Prober
from agent.platform_support.base import PlatformInfo
from agent.storage.local_db import LocalStore
from shared.models.diagnostic import DiagnosticResult, RunSource

__all__ = [
    "Clock",
    "SystemClock",
    "CollectorSet",
    "DiagnosticPipeline",
    "live_collector_set",
]


class Clock(Protocol):
    """A source of the current timezone-aware UTC time."""

    def now(self) -> datetime: ...


class SystemClock:
    """The real clock; tests inject a fixed clock instead."""

    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass(frozen=True)
class CollectorSet:
    """Zero-arg collector callables, injected so they can be simulated."""

    cpu: Callable[[], CpuInfo]
    memory: Callable[[], MemoryInfo]
    storage: Callable[[], list[VolumeInfo]]
    disks: Callable[[], list[PhysicalDiskInfo]]
    system: Callable[[], SystemInfo]
    gpus: Callable[[], list[GpuInfo]]
    network: Callable[[], NetworkInfo]


def live_collector_set(
    platform_info: PlatformInfo, settings: Settings
) -> CollectorSet:
    """Build the real collector set for the live ``scan``/``run`` pipeline."""
    return CollectorSet(
        cpu=lambda: collect_cpu(
            platform_info,
            sample_count=settings.cpu_sample_count,
            sample_interval_seconds=settings.cpu_sample_interval_seconds,
        ),
        memory=collect_memory,
        storage=collect_storage,
        disks=lambda: collect_physical_disks(platform_info),
        system=collect_system,
        gpus=lambda: collect_gpus(platform_info),
        network=lambda: collect_network(platform_info),
    )


class DiagnosticPipeline:
    """Runs the full diagnostic pipeline over injected providers."""

    def __init__(
        self,
        settings: Settings,
        collectors: CollectorSet,
        prober: Prober,
        evaluator: HealthEvaluator,
        clock: Clock,
    ) -> None:
        self._settings = settings
        self._collectors = collectors
        self._prober = prober
        self._evaluator = evaluator
        self._clock = clock

    def run(
        self,
        device_id: str | None,
        store: LocalStore | None,
        source: RunSource,
        *,
        enqueue: bool,
    ) -> DiagnosticResult:
        """Collect, diagnose, evaluate and (optionally) persist one run."""
        if device_id is None and store is not None:
            raise ValueError("a run without an identity cannot be persisted")

        collected = self._collect()
        diagnosis = NetworkDiagnostics(self._prober, self._settings).run(
            collected.network
        )
        result = evaluate_result(
            device_id=device_id,
            collected=collected,
            diagnosis=diagnosis,
            settings=self._settings,
            source=source,
            now=self._clock.now,
            evaluator=self._evaluator,
        )
        if store is not None:
            store.save_run(result, enqueue_event=enqueue)
        return result

    def _collect(self) -> Collected:
        return Collected(
            cpu=run_collector("cpu", self._collectors.cpu),
            memory=run_collector("memory", self._collectors.memory),
            storage=run_collector("storage", self._collectors.storage),
            system=run_collector("system", self._collectors.system),
            gpus=run_collector("gpus", self._collectors.gpus),
            disks=run_collector("disks", self._collectors.disks),
            network=run_collector("network", self._collectors.network),
        )
