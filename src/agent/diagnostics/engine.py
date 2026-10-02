"""Run collectors, network diagnostics and health rules into a result.

This is the read-only diagnostic engine used by the ``network`` and ``health``
commands (and reusable by ``scan`` later). It never imports the sync package, so
the local-first import boundary holds (design B.18).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from agent.collectors.base import CollectorResult, run_collector
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
from agent.diagnostics.facts import build_facts
from agent.diagnostics.health import HealthEvaluator
from agent.diagnostics.network_diagnostics import NetworkDiagnosis, NetworkDiagnostics
from agent.diagnostics.probes import Prober
from agent.diagnostics.rules import DiagnosticInput
from agent.platform_support.base import PlatformInfo
from shared.models.diagnostic import DiagnosticResult, Metric, RunSource
from shared.utils.ids import new_uuid7
from shared.utils.timeutil import to_iso

__all__ = ["Collected", "collect_all", "diagnose", "evaluate_result"]


class Collected:
    """Container of every collector result for one run."""

    def __init__(
        self,
        cpu: CollectorResult[CpuInfo],
        memory: CollectorResult[MemoryInfo],
        storage: CollectorResult[list[VolumeInfo]],
        system: CollectorResult[SystemInfo],
        gpus: CollectorResult[list[GpuInfo]],
        disks: CollectorResult[list[PhysicalDiskInfo]],
        network: CollectorResult[NetworkInfo],
    ) -> None:
        self.cpu = cpu
        self.memory = memory
        self.storage = storage
        self.system = system
        self.gpus = gpus
        self.disks = disks
        self.network = network


def collect_all(platform_info: PlatformInfo, settings: Settings) -> Collected:
    """Run every collector through the isolation boundary."""
    return Collected(
        cpu=run_collector(
            "cpu",
            lambda: collect_cpu(
                platform_info,
                sample_count=settings.cpu_sample_count,
                sample_interval_seconds=settings.cpu_sample_interval_seconds,
            ),
        ),
        memory=run_collector("memory", collect_memory),
        storage=run_collector("storage", collect_storage),
        system=run_collector("system", collect_system),
        gpus=run_collector("gpus", lambda: collect_gpus(platform_info)),
        disks=run_collector("disks", lambda: collect_physical_disks(platform_info)),
        network=run_collector("network", lambda: collect_network(platform_info)),
    )


def diagnose(
    collected: Collected, prober: Prober, settings: Settings
) -> NetworkDiagnosis:
    """Run network diagnostics over the collected network info."""
    return NetworkDiagnostics(prober, settings).run(collected.network)


def _metrics(collected: Collected, diagnosis: NetworkDiagnosis) -> tuple[Metric, ...]:
    metrics: list[Metric] = []
    if collected.cpu.has_data and collected.cpu.data is not None:
        metrics.append(
            Metric("cpu.usage_percent", collected.cpu.data.current_percent, "percent")
        )
        metrics.append(
            Metric(
                "cpu.average_percent", collected.cpu.data.average_percent, "percent"
            )
        )
    if collected.memory.has_data and collected.memory.data is not None:
        metrics.append(
            Metric("memory.usage_percent", collected.memory.data.percent, "percent")
        )
    if collected.storage.has_data and collected.storage.data is not None:
        for volume in collected.storage.data:
            metrics.append(
                Metric(
                    "storage.usage_percent",
                    volume.percent,
                    "percent",
                    {"volume": volume.mountpoint},
                )
            )
    if diagnosis.latency_avg_ms is not None:
        metrics.append(
            Metric("network.latency_avg_ms", diagnosis.latency_avg_ms, "milliseconds")
        )
    if diagnosis.packet_loss_percent is not None:
        metrics.append(
            Metric(
                "network.packet_loss_percent",
                diagnosis.packet_loss_percent,
                "percent",
            )
        )
    if collected.system.has_data and collected.system.data is not None:
        metrics.append(
            Metric(
                "system.uptime_seconds",
                float(collected.system.data.uptime_seconds),
                "seconds",
            )
        )
    return tuple(
        Metric(m.name, round(m.value, 1), m.unit, m.labels) for m in metrics
    )


def evaluate_result(
    *,
    device_id: str | None,
    collected: Collected,
    diagnosis: NetworkDiagnosis,
    settings: Settings,
    source: RunSource,
    now: Callable[[], datetime],
    evaluator: HealthEvaluator | None = None,
) -> DiagnosticResult:
    """Build a full ``DiagnosticResult`` (no persistence)."""
    started = now()
    checked_at = to_iso(started)
    rule_input = DiagnosticInput(
        cpu=collected.cpu,
        memory=collected.memory,
        storage=collected.storage,
        disks=collected.disks,
        system=collected.system,
        gpus=collected.gpus,
        network=collected.network,
        diagnosis=diagnosis,
        checked_at=checked_at,
    )
    evaluation = (evaluator or HealthEvaluator()).evaluate(
        rule_input, settings.thresholds
    )
    facts = build_facts(
        cpu=collected.cpu,
        memory=collected.memory,
        storage=collected.storage,
        system=collected.system,
        gpus=collected.gpus,
        disks=collected.disks,
        network=collected.network,
        diagnosis=diagnosis,
    )
    finished = now()
    return DiagnosticResult(
        run_id=new_uuid7(),
        device_id=device_id,
        started_at=checked_at,
        finished_at=to_iso(finished),
        source=source,
        status=evaluation.status,
        network_status=diagnosis.status,
        checks=evaluation.checks,
        alerts=evaluation.alerts,
        metrics=_metrics(collected, diagnosis),
        facts=facts,
    )
