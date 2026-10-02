"""Network diagnostics: run probes and classify connectivity (design B.7).

Classification is first-match (UNKNOWN, OFFLINE, UNSTABLE, DEGRADED, HEALTHY).
Evidence refers to interfaces by COUNT only, never by name (review F3/finding 3),
so interface names stay in local facts and never reach uploaded evidence.
Gateway IPs appear only in local evidence and are stripped before upload.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from agent.collectors.base import CollectorResult
from agent.collectors.network import NetworkInfo
from agent.config.settings import Settings
from agent.diagnostics.probes import ProbeOutcome, Prober, ProbeResult, ResolveResult
from shared.models.diagnostic import NetworkStatus

__all__ = ["NetworkDiagnosis", "NetworkDiagnostics"]

DnsState = Literal["OK", "PARTIAL", "FAILED", "UNKNOWN"]


@dataclass(frozen=True)
class NetworkDiagnosis:
    """Outcome of the network diagnostics run."""

    local_network_available: bool | None
    usable_interface_count: int | None  # None when interface data is missing
    gateway_reachable: bool | None
    gateways_known: bool | None
    internet_available: bool
    packet_loss_percent: float | None
    latency_avg_ms: float | None
    latency_min_ms: float | None
    latency_max_ms: float | None
    dns_state: DnsState
    status: NetworkStatus
    evidence: tuple[str, ...]
    possible_causes: tuple[str, ...]
    probes: tuple[ProbeResult, ...]
    resolutions: tuple[ResolveResult, ...]


_LINK_LOCAL_PREFIXES = ("169.254.", "fe80:")


def _usable_interface_count(network: NetworkInfo) -> int:
    count = 0
    for iface in network.interfaces:
        if not iface.is_up:
            continue
        name_lower = iface.name.lower()
        if "loopback" in name_lower or name_lower.startswith("lo"):
            continue
        addresses = list(iface.ipv4) + list(iface.ipv6)
        has_routable = any(
            not addr.lower().startswith(_LINK_LOCAL_PREFIXES) for addr in addresses
        )
        if has_routable:
            count += 1
    return count


class NetworkDiagnostics:
    """Run gateway/internet/DNS probes and classify the network."""

    def __init__(self, prober: Prober, settings: Settings) -> None:
        self._prober = prober
        self._settings = settings

    def run(self, network: CollectorResult[NetworkInfo]) -> NetworkDiagnosis:
        settings = self._settings
        timeout = settings.network_probe_timeout_seconds
        count = settings.network_probe_count

        info = network.data
        has_interface_data = network.has_data and info is not None

        # --- Gateways -----------------------------------------------------
        gateways_known: bool | None
        gateway_reachable: bool | None
        gateway_probes: list[ProbeResult] = []
        gateway_evidence: list[str] = []
        if info is None or info.gateways is None:
            gateways_known = None
            gateway_reachable = None
        elif len(info.gateways) == 0:
            gateways_known = False
            gateway_reachable = None
        else:
            gateways_known = True
            for gw in info.gateways[:2]:
                outcomes = [
                    self._prober.icmp_ping(gw, timeout) for _ in range(count)
                ]
                gateway_probes.extend(outcomes)
                reachable = any(o.outcome is ProbeOutcome.SUCCESS for o in outcomes)
                if reachable:
                    rtt = next(
                        (
                            o.rtt_ms
                            for o in outcomes
                            if o.outcome is ProbeOutcome.SUCCESS
                            and o.rtt_ms is not None
                        ),
                        None,
                    )
                    suffix = f" ({rtt:.0f} ms)" if rtt is not None else ""
                    gateway_evidence.append(f"Gateway {gw} reachable{suffix}")
                elif any(o.outcome is ProbeOutcome.NO_REPLY for o in outcomes):
                    gateway_evidence.append(f"Gateway {gw} did not reply")
            all_error = bool(gateway_probes) and all(
                o.outcome is ProbeOutcome.ERROR for o in gateway_probes
            )
            any_success = any(
                o.outcome is ProbeOutcome.SUCCESS for o in gateway_probes
            )
            any_no_reply = any(
                o.outcome is ProbeOutcome.NO_REPLY for o in gateway_probes
            )
            if any_success:
                gateway_reachable = True
            elif any_no_reply and not all_error:
                gateway_reachable = False
            else:
                gateway_reachable = None

        # --- Internet -----------------------------------------------------
        internet_probes: list[ProbeResult] = []
        for host, port in settings.internet_targets:
            for _ in range(count):
                internet_probes.append(
                    self._prober.tcp_connect(host, port, timeout)
                )
        internet_success = [
            p for p in internet_probes if p.outcome is ProbeOutcome.SUCCESS
        ]
        internet_available = bool(internet_success)
        total_internet = len(internet_probes)
        failed_internet = total_internet - len(internet_success)
        packet_loss: float | None = (
            round(failed_internet / total_internet * 100, 1)
            if total_internet
            else None
        )
        rtts = [p.rtt_ms for p in internet_success if p.rtt_ms is not None]
        latency_avg = round(sum(rtts) / len(rtts), 1) if rtts else None
        latency_min = round(min(rtts), 1) if rtts else None
        latency_max = round(max(rtts), 1) if rtts else None

        # --- DNS ----------------------------------------------------------
        resolutions = [
            self._prober.resolve(host, timeout)
            for host in settings.dns_test_hostnames
        ]
        dns_state = _dns_state(resolutions)

        # --- Classification ----------------------------------------------
        all_internet_error = bool(internet_probes) and all(
            p.outcome is ProbeOutcome.ERROR for p in internet_probes
        )
        all_dns_error = bool(resolutions) and all(
            r.outcome is ProbeOutcome.ERROR for r in resolutions
        )

        usable_count = _usable_interface_count(info) if info is not None else 0
        local_network_available: bool | None
        if not has_interface_data:
            local_network_available = None
        else:
            local_network_available = (usable_count > 0) and (
                gateway_reachable is True or internet_available
            )

        status = _classify(
            all_internet_error=all_internet_error,
            all_dns_error=all_dns_error,
            has_interface_data=has_interface_data,
            usable_count=usable_count,
            internet_available=internet_available,
            packet_loss=packet_loss,
            latency_avg=latency_avg,
            dns_state=dns_state,
            thresholds_loss_unstable=settings.thresholds.packet_loss_unstable_percent,
            thresholds_loss_warn=settings.thresholds.packet_loss_warning_percent,
            thresholds_latency=settings.thresholds.latency_warning_ms,
        )

        evidence = _build_evidence(
            usable_count=usable_count,
            has_interface_data=has_interface_data,
            gateway_evidence=gateway_evidence,
            gateway_reachable=gateway_reachable,
            gateways_known=gateways_known,
            internet_available=internet_available,
            failed_internet=failed_internet,
            total_internet=total_internet,
            packet_loss=packet_loss,
            latency_avg=latency_avg,
            dns_state=dns_state,
        )
        causes = _possible_causes(
            status=status,
            internet_available=internet_available,
            dns_state=dns_state,
            gateway_reachable=gateway_reachable,
            gateways_known=gateways_known,
        )

        all_probes = tuple(gateway_probes) + tuple(internet_probes)
        return NetworkDiagnosis(
            local_network_available=local_network_available,
            usable_interface_count=usable_count if has_interface_data else None,
            gateway_reachable=gateway_reachable,
            gateways_known=gateways_known,
            internet_available=internet_available,
            packet_loss_percent=packet_loss,
            latency_avg_ms=latency_avg,
            latency_min_ms=latency_min,
            latency_max_ms=latency_max,
            dns_state=dns_state,
            status=status,
            evidence=tuple(evidence),
            possible_causes=tuple(causes),
            probes=all_probes,
            resolutions=tuple(resolutions),
        )


def _dns_state(resolutions: list[ResolveResult]) -> DnsState:
    if not resolutions:
        return "UNKNOWN"
    if all(r.outcome is ProbeOutcome.ERROR for r in resolutions):
        return "UNKNOWN"
    successes = sum(1 for r in resolutions if r.outcome is ProbeOutcome.SUCCESS)
    if successes == len(resolutions):
        return "OK"
    if successes == 0:
        return "FAILED"
    return "PARTIAL"


def _classify(
    *,
    all_internet_error: bool,
    all_dns_error: bool,
    has_interface_data: bool,
    usable_count: int,
    internet_available: bool,
    packet_loss: float | None,
    latency_avg: float | None,
    dns_state: DnsState,
    thresholds_loss_unstable: float,
    thresholds_loss_warn: float,
    thresholds_latency: float,
) -> NetworkStatus:
    # 1. UNKNOWN: nothing could execute.
    if all_internet_error and all_dns_error:
        return NetworkStatus.UNKNOWN
    # 2. OFFLINE: interface data present but no usable interface, or no internet.
    if (has_interface_data and usable_count == 0) or not internet_available:
        return NetworkStatus.OFFLINE
    # 3. UNSTABLE: packet loss at or above the unstable threshold.
    if packet_loss is not None and packet_loss >= thresholds_loss_unstable:
        return NetworkStatus.UNSTABLE
    # 4. DEGRADED: loss >= warning, latency over the warning, or DNS not OK.
    loss_warn = packet_loss is not None and packet_loss >= thresholds_loss_warn
    latency_warn = latency_avg is not None and latency_avg > thresholds_latency
    if loss_warn or latency_warn or dns_state in ("PARTIAL", "FAILED"):
        return NetworkStatus.DEGRADED
    # 5. HEALTHY.
    return NetworkStatus.HEALTHY


def _build_evidence(
    *,
    usable_count: int,
    has_interface_data: bool,
    gateway_evidence: list[str],
    gateway_reachable: bool | None,
    gateways_known: bool | None,
    internet_available: bool,
    failed_internet: int,
    total_internet: int,
    packet_loss: float | None,
    latency_avg: float | None,
    dns_state: DnsState,
) -> list[str]:
    evidence: list[str] = []
    if has_interface_data:
        noun = "interface" if usable_count == 1 else "interfaces"
        evidence.append(f"{usable_count} usable {noun}")
    else:
        evidence.append("interface data unavailable")
    evidence.extend(gateway_evidence)
    if gateways_known is None:
        evidence.append("Gateway information unavailable")
    elif gateways_known is False:
        evidence.append("No default gateway configured")
    elif gateway_reachable is None and gateways_known:
        evidence.append("Gateway does not answer ICMP; may be filtered")
    if gateway_reachable is None and internet_available:
        evidence.append(
            "Gateway does not answer ICMP; internet reachable, likely ICMP filtered"
        )
    if total_internet:
        if internet_available:
            evidence.append("Internet reachable")
        else:
            evidence.append("Internet unreachable")
        if packet_loss is not None:
            evidence.append(
                f"{failed_internet}/{total_internet} internet probes failed "
                f"({packet_loss:.1f}% loss)"
            )
    if latency_avg is not None:
        evidence.append(f"Average latency {latency_avg:.1f} ms")
    evidence.append(f"DNS resolution: {dns_state}")
    return evidence


def _possible_causes(
    *,
    status: NetworkStatus,
    internet_available: bool,
    dns_state: DnsState,
    gateway_reachable: bool | None,
    gateways_known: bool | None,
) -> list[str]:
    if status is NetworkStatus.HEALTHY:
        return []
    causes: list[str] = []
    if status is NetworkStatus.UNKNOWN:
        return [
            "Probes could not execute (missing ping tool or blocked sockets)",
            "Local security policy may be blocking outbound diagnostics",
        ]
    if not internet_available:
        if gateways_known is False or gateway_reachable is False:
            causes.extend(
                [
                    "Local gateway or router is unreachable",
                    "Physical link or Wi-Fi association problem",
                ]
            )
        else:
            causes.extend(
                [
                    "ISP or upstream outage",
                    "Firewall blocking outbound connections",
                ]
            )
    if internet_available and dns_state in ("PARTIAL", "FAILED"):
        causes.extend(
            [
                "DNS server unreachable or misconfigured",
                "ISP DNS outage",
                "Router DNS relay issue",
            ]
        )
    if status is NetworkStatus.UNSTABLE and not causes:
        causes.extend(
            [
                "Congested or unreliable link (high probe loss)",
                "Wireless interference or weak signal",
            ]
        )
    if status is NetworkStatus.DEGRADED and not causes:
        causes.extend(
            [
                "Elevated latency or intermittent loss on the path",
                "Upstream congestion",
            ]
        )
    return causes
