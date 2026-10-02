"""Deterministic health rules (design B.7).

Each rule is a pure function ``(DiagnosticInput, Thresholds) -> RuleOutcome``
that owns exactly one check name. ``RULES`` fixes evaluation order and asserts
unique check names at import. A rule whose input is missing returns a SKIPPED
check and no alert.

Privacy: physical disks are referenced by position (``disk{index}``) only;
model names (``friendly_name``) and GPU names never enter checks, alerts or
metrics (review F3). Storage emits exactly one ``storage.usage`` check whose
status is the worst over all volumes, with one alert per offending volume
(review F14).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agent.collectors.base import CollectorResult, CollectorStatus
from agent.collectors.cpu import CpuInfo
from agent.collectors.hardware import GpuInfo, PhysicalDiskInfo
from agent.collectors.memory import MemoryInfo
from agent.collectors.network import NetworkInfo
from agent.collectors.storage import VolumeInfo
from agent.collectors.system import SystemInfo
from agent.config.settings import Thresholds
from agent.diagnostics.network_diagnostics import NetworkDiagnosis
from shared.models.diagnostic import (
    Alert,
    Check,
    CheckStatus,
    NetworkStatus,
    Severity,
)

__all__ = [
    "DiagnosticInput",
    "RuleOutcome",
    "Rule",
    "RULES",
]


@dataclass(frozen=True)
class DiagnosticInput:
    """Everything the rules read: collector results plus the network diagnosis."""

    cpu: CollectorResult[CpuInfo]
    memory: CollectorResult[MemoryInfo]
    storage: CollectorResult[list[VolumeInfo]]
    disks: CollectorResult[list[PhysicalDiskInfo]]
    system: CollectorResult[SystemInfo]
    gpus: CollectorResult[list[GpuInfo]]
    network: CollectorResult[NetworkInfo]
    diagnosis: NetworkDiagnosis
    checked_at: str


@dataclass(frozen=True)
class RuleOutcome:
    """One check and zero or more alerts produced by a rule."""

    check: Check
    alerts: tuple[Alert, ...] = field(default_factory=tuple)


Rule = Callable[[DiagnosticInput, Thresholds], RuleOutcome]


def _skipped(name: str, when: str, reason: str) -> RuleOutcome:
    return RuleOutcome(
        Check(name=name, status=CheckStatus.SKIPPED, summary=reason, evidence=(),
              checked_at=when)
    )


# --- Storage usage (single check, worst-over-volumes) --------------------

_DISK_WARN_REC = (
    "Free space on the volume or extend it; check large temporary or log folders."
)


def storage_usage(data: DiagnosticInput, thresholds: Thresholds) -> RuleOutcome:
    name = "storage.usage"
    if not data.storage.has_data or data.storage.data is None:
        return _skipped(name, data.checked_at, "storage data unavailable")
    volumes = data.storage.data
    if not volumes:
        return RuleOutcome(
            Check(name, CheckStatus.PASS, "no fixed volumes detected", (),
                  data.checked_at)
        )
    alerts: list[Alert] = []
    evidence: list[str] = []
    worst = CheckStatus.PASS
    for volume in volumes:
        evidence.append(f"{volume.mountpoint} at {volume.percent:.1f}% used")
        if volume.percent >= thresholds.disk_usage_critical_percent:
            worst = CheckStatus.FAIL
            alerts.append(
                Alert(
                    rule_id="DISK_SPACE_CRITICAL",
                    severity=Severity.CRITICAL,
                    message=(
                        f"{volume.mountpoint} is critically full "
                        f"({volume.percent:.1f}%)"
                    ),
                    subject=volume.mountpoint,
                    recommendation=_DISK_WARN_REC,
                )
            )
        elif volume.percent >= thresholds.disk_usage_warning_percent:
            if worst is not CheckStatus.FAIL:
                worst = CheckStatus.WARN
            alerts.append(
                Alert(
                    rule_id="DISK_SPACE_WARNING",
                    severity=Severity.WARNING,
                    message=(
                        f"{volume.mountpoint} is running low on space "
                        f"({volume.percent:.1f}%)"
                    ),
                    subject=volume.mountpoint,
                    recommendation=_DISK_WARN_REC,
                )
            )
    summary = {
        CheckStatus.PASS: "all volumes within thresholds",
        CheckStatus.WARN: "one or more volumes low on space",
        CheckStatus.FAIL: "one or more volumes critically full",
    }[worst]
    return RuleOutcome(
        Check(name, worst, summary, tuple(evidence), data.checked_at),
        tuple(alerts),
    )


# --- Disk health ---------------------------------------------------------


def disk_health(data: DiagnosticInput, thresholds: Thresholds) -> RuleOutcome:
    name = "storage.health"
    if not data.disks.has_data or data.disks.data is None:
        return _skipped(name, data.checked_at, "physical disk data unavailable")
    disks = data.disks.data
    if not disks:
        return RuleOutcome(
            Check(name, CheckStatus.PASS, "no physical disks reported", (),
                  data.checked_at)
        )
    alerts: list[Alert] = []
    evidence: list[str] = []
    status = CheckStatus.PASS
    for index, disk in enumerate(disks):
        label = f"disk{index}"
        healthy = disk.health_status.lower() in ("healthy", "unknown")
        evidence.append(
            f"{label} ({disk.media_type}, {disk.bus_type}): "
            f"HealthStatus={disk.health_status}"
        )
        if not healthy:
            status = CheckStatus.WARN
            alerts.append(
                Alert(
                    rule_id="DISK_HEALTH_WARNING",
                    severity=Severity.WARNING,
                    message=f"{label} reports health {disk.health_status}",
                    subject=label,
                    recommendation=(
                        "Back up data and plan to replace the drive; "
                        "run the vendor diagnostic tool."
                    ),
                )
            )
    summary = (
        "all physical disks healthy"
        if status is CheckStatus.PASS
        else "one or more physical disks report a problem"
    )
    return RuleOutcome(
        Check(name, status, summary, tuple(evidence), data.checked_at),
        tuple(alerts),
    )


# --- Memory --------------------------------------------------------------


def memory_pressure(data: DiagnosticInput, thresholds: Thresholds) -> RuleOutcome:
    name = "memory.usage"
    if not data.memory.has_data or data.memory.data is None:
        return _skipped(name, data.checked_at, "memory data unavailable")
    percent = data.memory.data.percent
    evidence = (f"memory at {percent:.1f}% used",)
    if percent >= thresholds.memory_usage_warning_percent:
        return RuleOutcome(
            Check(name, CheckStatus.WARN, "memory usage is high", evidence,
                  data.checked_at),
            (
                Alert(
                    rule_id="MEMORY_PRESSURE",
                    severity=Severity.WARNING,
                    message=f"Memory usage is high ({percent:.1f}%)",
                    subject=None,
                    recommendation=(
                        "Close memory-heavy applications or add RAM if this "
                        "persists under normal load."
                    ),
                ),
            ),
        )
    return RuleOutcome(
        Check(name, CheckStatus.PASS, "memory usage within threshold", evidence,
              data.checked_at)
    )


# --- CPU -----------------------------------------------------------------


def high_cpu_usage(data: DiagnosticInput, thresholds: Thresholds) -> RuleOutcome:
    name = "cpu.usage"
    if not data.cpu.has_data or data.cpu.data is None:
        return _skipped(name, data.checked_at, "cpu data unavailable")
    average = data.cpu.data.average_percent
    evidence = (f"average CPU over the sampling window is {average:.1f}%",)
    if average >= thresholds.cpu_usage_warning_percent:
        return RuleOutcome(
            Check(name, CheckStatus.WARN, "sustained CPU usage is high", evidence,
                  data.checked_at),
            (
                Alert(
                    rule_id="HIGH_CPU_USAGE",
                    severity=Severity.WARNING,
                    message=f"Sustained CPU usage is high ({average:.1f}%)",
                    subject=None,
                    recommendation=(
                        "Identify the busiest process; a sustained high load "
                        "may indicate a runaway task."
                    ),
                ),
            ),
        )
    return RuleOutcome(
        Check(name, CheckStatus.PASS, "cpu usage within threshold", evidence,
              data.checked_at)
    )


# --- Connectivity (two mutually-exclusive rules) -------------------------


def _local_network_failure_condition(diag: NetworkDiagnosis) -> bool:
    """The precise LOCAL_NETWORK_FAILURE condition (design B.7).

    internet unreachable AND status != UNKNOWN AND (no usable interface while
    interface data is present OR gateways == [] OR gateway_reachable is False).
    """
    if diag.internet_available or diag.status is NetworkStatus.UNKNOWN:
        return False
    no_usable_interface = (
        diag.usable_interface_count is not None and diag.usable_interface_count == 0
    )
    return (
        no_usable_interface
        or diag.gateways_known is False
        or diag.gateway_reachable is False
    )


def local_network_failure(
    data: DiagnosticInput, thresholds: Thresholds
) -> RuleOutcome:
    name = "network.gateway"
    diag = data.diagnosis
    if diag.status is NetworkStatus.UNKNOWN:
        return _skipped(name, data.checked_at, "network probes could not execute")
    # Gateway status unknown -> SKIPPED with a precise reason.
    if diag.gateways_known is None:
        return _skipped(name, data.checked_at, "gateway information unavailable")
    if (
        diag.gateways_known
        and diag.gateway_reachable is None
    ):
        return _skipped(name, data.checked_at, "gateway probe could not execute")
    if diag.internet_available:
        return RuleOutcome(
            Check(name, CheckStatus.PASS, "local network reachable",
                  _gateway_evidence(diag), data.checked_at)
        )
    if _local_network_failure_condition(diag):
        return RuleOutcome(
            Check(name, CheckStatus.FAIL, "local network failure",
                  _gateway_evidence(diag), data.checked_at),
            (
                Alert(
                    rule_id="LOCAL_NETWORK_FAILURE",
                    severity=Severity.CRITICAL,
                    message="Local network or gateway is unreachable",
                    subject=None,
                    recommendation=(
                        "Check the physical link, Wi-Fi association and the "
                        "local router or gateway."
                    ),
                ),
            ),
        )
    return RuleOutcome(
        Check(name, CheckStatus.PASS, "local network reachable",
              _gateway_evidence(diag), data.checked_at)
    )


def internet_connectivity_failure(
    data: DiagnosticInput, thresholds: Thresholds
) -> RuleOutcome:
    name = "network.internet"
    diag = data.diagnosis
    if diag.status is NetworkStatus.UNKNOWN:
        return _skipped(name, data.checked_at, "network probes could not execute")
    if diag.internet_available:
        return RuleOutcome(
            Check(name, CheckStatus.PASS, "internet reachable", ("Internet reachable",),
                  data.checked_at)
        )
    if _local_network_failure_condition(diag):
        # LOCAL_NETWORK_FAILURE owns this case; this rule stays PASS/SKIPPED-free
        # by reporting SKIPPED to keep the two rules mutually exclusive.
        return _skipped(
            name, data.checked_at, "covered by local network failure"
        )
    evidence = ["Internet unreachable"]
    if diag.gateway_reachable is None:
        evidence.append("gateway status unknown")
    return RuleOutcome(
        Check(name, CheckStatus.FAIL, "internet connectivity failure",
              tuple(evidence), data.checked_at),
        (
            Alert(
                rule_id="INTERNET_CONNECTIVITY_FAILURE",
                severity=Severity.WARNING,
                message="Internet is unreachable while the local network looks up",
                subject=None,
                recommendation=(
                    "Check upstream connectivity with the ISP; local network "
                    "appears functional."
                ),
            ),
        ),
    )


def _gateway_evidence(diag: NetworkDiagnosis) -> tuple[str, ...]:
    if diag.gateway_reachable is True:
        return ("gateway reachable",)
    if diag.gateway_reachable is False:
        return ("gateway did not reply",)
    return ("gateway status unknown",)


# --- DNS -----------------------------------------------------------------


def dns_failure(data: DiagnosticInput, thresholds: Thresholds) -> RuleOutcome:
    name = "network.dns"
    diag = data.diagnosis
    if not diag.internet_available:
        return _skipped(name, data.checked_at, "internet unreachable; DNS not assessed")
    evidence = (f"DNS resolution: {diag.dns_state}",)
    if diag.dns_state in ("FAILED", "PARTIAL"):
        return RuleOutcome(
            Check(name, CheckStatus.WARN, "DNS resolution problems", evidence,
                  data.checked_at),
            (
                Alert(
                    rule_id="DNS_FAILURE",
                    severity=Severity.WARNING,
                    message=f"DNS resolution is {diag.dns_state.lower()}",
                    subject=None,
                    recommendation=(
                        "Check the configured DNS servers; try an alternate "
                        "resolver to confirm."
                    ),
                ),
            ),
        )
    return RuleOutcome(
        Check(name, CheckStatus.PASS, "DNS resolution healthy", evidence,
              data.checked_at)
    )


# --- Latency -------------------------------------------------------------


def high_latency(data: DiagnosticInput, thresholds: Thresholds) -> RuleOutcome:
    name = "network.latency"
    diag = data.diagnosis
    if not diag.internet_available or diag.latency_avg_ms is None:
        return _skipped(name, data.checked_at, "latency not measured")
    avg = diag.latency_avg_ms
    evidence = (f"average latency {avg:.1f} ms",)
    if avg > thresholds.latency_warning_ms:
        return RuleOutcome(
            Check(name, CheckStatus.WARN, "high network latency", evidence,
                  data.checked_at),
            (
                Alert(
                    rule_id="HIGH_LATENCY",
                    severity=Severity.WARNING,
                    message=f"Network latency is high ({avg:.1f} ms)",
                    subject=None,
                    recommendation=(
                        "Check for congestion or a saturated uplink; test a "
                        "wired connection if on Wi-Fi."
                    ),
                ),
            ),
        )
    return RuleOutcome(
        Check(name, CheckStatus.PASS, "latency within threshold", evidence,
              data.checked_at)
    )


# --- Packet loss ---------------------------------------------------------


def packet_loss(data: DiagnosticInput, thresholds: Thresholds) -> RuleOutcome:
    name = "network.packet_loss"
    diag = data.diagnosis
    if not diag.internet_available or diag.packet_loss_percent is None:
        return _skipped(name, data.checked_at, "packet loss not measured")
    loss = diag.packet_loss_percent
    evidence = (f"probe failure rate {loss:.1f}%",)
    if loss >= thresholds.packet_loss_warning_percent:
        return RuleOutcome(
            Check(name, CheckStatus.WARN, "elevated probe loss", evidence,
                  data.checked_at),
            (
                Alert(
                    rule_id="PACKET_LOSS",
                    severity=Severity.WARNING,
                    message=f"Elevated probe loss ({loss:.1f}%)",
                    subject=None,
                    recommendation=(
                        "Investigate link quality; wireless interference or a "
                        "failing cable can cause loss."
                    ),
                ),
            ),
        )
    return RuleOutcome(
        Check(name, CheckStatus.PASS, "probe loss within threshold", evidence,
              data.checked_at)
    )


# --- Collector failure (informational) -----------------------------------


def collector_failure(data: DiagnosticInput, thresholds: Thresholds) -> RuleOutcome:
    name = "agent.collectors"
    results: list[tuple[str, CollectorResult[Any]]] = [
        ("cpu", data.cpu),
        ("memory", data.memory),
        ("storage", data.storage),
        ("disks", data.disks),
        ("system", data.system),
        ("gpus", data.gpus),
        ("network", data.network),
    ]
    failed = [n for n, r in results if r.status is CollectorStatus.FAILED]
    if not failed:
        return RuleOutcome(
            Check(name, CheckStatus.PASS, "all collectors ran", (), data.checked_at)
        )
    evidence = tuple(f"{n} collector failed" for n in failed)
    return RuleOutcome(
        Check(name, CheckStatus.WARN, "one or more collectors failed", evidence,
              data.checked_at),
        (
            Alert(
                rule_id="COLLECTOR_FAILURE",
                severity=Severity.INFO,
                message=f"{len(failed)} collector(s) failed: {', '.join(failed)}",
                subject=None,
                recommendation=(
                    "Some data could not be collected; see the log for details."
                ),
            ),
        ),
    )


RULES: tuple[Rule, ...] = (
    storage_usage,
    disk_health,
    memory_pressure,
    high_cpu_usage,
    local_network_failure,
    internet_connectivity_failure,
    dns_failure,
    high_latency,
    packet_loss,
    collector_failure,
)

# Each rule owns exactly one check name; enforce uniqueness at import.
_CHECK_NAMES = {
    "storage.usage",
    "storage.health",
    "memory.usage",
    "cpu.usage",
    "network.gateway",
    "network.internet",
    "network.dns",
    "network.latency",
    "network.packet_loss",
    "agent.collectors",
}
assert len(_CHECK_NAMES) == len(RULES), (  # noqa: S101 - import-time invariant
    "rule check names must be unique"
)
