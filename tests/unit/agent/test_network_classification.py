"""Tests for network classification and the first-match rules (design B.7)."""

from __future__ import annotations

from collections.abc import Callable

from agent.collectors.base import CollectorResult, CollectorStatus
from agent.collectors.network import InterfaceInfo, NetworkInfo
from agent.config.settings import load_settings
from agent.diagnostics.network_diagnostics import NetworkDiagnostics
from agent.diagnostics.probes import (
    ProbeOutcome,
    ProbeResult,
    ResolveResult,
)
from shared.models.diagnostic import NetworkStatus


def _settings():
    return load_settings(
        env={
            "INTERNET_TARGETS": "1.1.1.1:443,8.8.8.8:443",
            "DNS_TEST_HOSTNAMES": "example.com,aws.amazon.com",
            "NETWORK_PROBE_COUNT": "2",
        }
    )


class FakeProber:
    """Prober with injectable outcome functions (never touches the network)."""

    def __init__(
        self,
        ping: Callable[[str], ProbeOutcome],
        tcp: Callable[[str], ProbeOutcome],
        dns: Callable[[str], ProbeOutcome],
        *,
        tcp_rtt: float | None = 20.0,
    ) -> None:
        self._ping = ping
        self._tcp = tcp
        self._dns = dns
        self._tcp_rtt = tcp_rtt

    def icmp_ping(self, host: str, timeout_s: float) -> ProbeResult:
        outcome = self._ping(host)
        rtt = 1.0 if outcome is ProbeOutcome.SUCCESS else None
        return ProbeResult(host, outcome, rtt, "")

    def tcp_connect(self, host: str, port: int, timeout_s: float) -> ProbeResult:
        outcome = self._tcp(host)
        rtt = self._tcp_rtt if outcome is ProbeOutcome.SUCCESS else None
        return ProbeResult(host, outcome, rtt, "")

    def resolve(self, hostname: str, timeout_s: float) -> ResolveResult:
        outcome = self._dns(hostname)
        addrs = ("1.2.3.4",) if outcome is ProbeOutcome.SUCCESS else ()
        return ResolveResult(hostname, outcome, addrs, 1.0)


def _network(
    *,
    gateways: tuple[str, ...] | None = ("10.0.0.1",),
    usable: bool = True,
    status: CollectorStatus = CollectorStatus.OK,
) -> CollectorResult[NetworkInfo]:
    if status is CollectorStatus.FAILED:
        return CollectorResult("network", status, None, ("boom",), 1)
    interfaces = (
        (
            InterfaceInfo("Ethernet", True, 1000, ("10.0.0.5",), ()),
        )
        if usable
        else (InterfaceInfo("Ethernet", False, None, (), ()),)
    )
    info = NetworkInfo(
        hostname="host",
        interfaces=interfaces,
        gateways=gateways,
        dns_servers=("10.0.0.1",) if gateways else (),
    )
    return CollectorResult("network", status, info, (), 1)


def _run(prober: FakeProber, network: CollectorResult[NetworkInfo]):
    return NetworkDiagnostics(prober, _settings()).run(network)


def _OK(host: str) -> ProbeOutcome:
    return ProbeOutcome.SUCCESS


def _NO(host: str) -> ProbeOutcome:
    return ProbeOutcome.NO_REPLY


def _ERR(host: str) -> ProbeOutcome:
    return ProbeOutcome.ERROR


def test_healthy() -> None:
    diag = _run(FakeProber(_OK, _OK, _OK), _network())
    assert diag.status is NetworkStatus.HEALTHY
    assert diag.internet_available is True
    assert diag.packet_loss_percent == 0.0


def test_unknown_all_error() -> None:
    diag = _run(FakeProber(_ERR, _ERR, _ERR), _network())
    assert diag.status is NetworkStatus.UNKNOWN


def test_offline_no_internet() -> None:
    diag = _run(FakeProber(_OK, _NO, _OK), _network())
    assert diag.status is NetworkStatus.OFFLINE
    assert diag.internet_available is False


def test_offline_no_usable_interface() -> None:
    diag = _run(FakeProber(_NO, _NO, _NO), _network(usable=False))
    assert diag.status is NetworkStatus.OFFLINE


def test_unstable_high_loss() -> None:
    # One target up, one down => 50% loss (>= 30% unstable threshold).
    def tcp(host: str) -> ProbeOutcome:
        return ProbeOutcome.SUCCESS if host == "1.1.1.1" else ProbeOutcome.NO_REPLY

    diag = _run(FakeProber(_OK, tcp, _OK), _network())
    assert diag.status is NetworkStatus.UNSTABLE


def test_degraded_dns_partial() -> None:
    def dns(host: str) -> ProbeOutcome:
        return ProbeOutcome.SUCCESS if host == "example.com" else ProbeOutcome.NO_REPLY

    diag = _run(FakeProber(_OK, _OK, dns), _network())
    assert diag.status is NetworkStatus.DEGRADED
    assert diag.dns_state == "PARTIAL"


def test_degraded_high_latency() -> None:
    prober = FakeProber(_OK, _OK, _OK, tcp_rtt=500.0)
    diag = _run(prober, _network())
    assert diag.status is NetworkStatus.DEGRADED


def test_evidence_uses_interface_count_not_name() -> None:
    diag = _run(FakeProber(_OK, _OK, _OK), _network())
    joined = " ".join(diag.evidence)
    assert "usable interface" in joined
    assert "Ethernet" not in joined


def test_gateway_unknown_when_all_ping_error() -> None:
    diag = _run(FakeProber(_ERR, _OK, _OK), _network())
    # Gateway probes all ERROR -> gateway_reachable unknown (None).
    assert diag.gateway_reachable is None


def test_failed_collector_classifies_on_probes() -> None:
    net = _network(status=CollectorStatus.FAILED)
    # A FAILED network collector with working probes is not forced OFFLINE.
    diag = _run(FakeProber(_OK, _OK, _OK), net)
    assert diag.status is NetworkStatus.HEALTHY
