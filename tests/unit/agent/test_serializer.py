"""Serializer tests: the privacy IP scrubber and the M3 sentinel (A.5 #25).

The sentinel builds an event whose evidence deliberately contains an interface
name, an IPv6 link-local with a zone id, an IPv6 address, an IPv4 address, and
the safe strings ``16:42:03`` and ``C:\\``. None of the network identifiers may
appear in ``json.dumps(build_event(result))``, while the safe strings survive.
"""

from __future__ import annotations

import json

from agent.collectors.base import run_collector
from agent.collectors.cpu import CpuInfo
from agent.collectors.memory import MemoryInfo
from agent.collectors.network import InterfaceInfo, NetworkInfo
from agent.collectors.storage import VolumeInfo
from agent.collectors.system import SystemInfo
from agent.config.settings import load_settings
from agent.diagnostics.engine import Collected, diagnose, evaluate_result
from agent.diagnostics.probes import ProbeOutcome, ProbeResult, ResolveResult
from agent.sync.serializer import build_event, build_registration, scrub_ips
from shared.models.diagnostic import (
    Alert,
    Check,
    CheckStatus,
    DiagnosticResult,
    HealthStatus,
    Metric,
    NetworkStatus,
    RunSource,
    Severity,
)
from shared.schemas.device import validate_device_registration
from shared.schemas.telemetry import validate_event
from shared.utils.ids import new_uuid7
from shared.utils.timeutil import to_iso, utc_now


class _OfflineProber:
    """A prober that reports everything unreachable (offline fixture)."""

    def icmp_ping(self, host: str, timeout_s: float) -> ProbeResult:
        return ProbeResult(host, ProbeOutcome.NO_REPLY, None, "unreachable")

    def tcp_connect(self, host: str, port: int, timeout_s: float) -> ProbeResult:
        return ProbeResult(host, ProbeOutcome.NO_REPLY, None, "refused")

    def resolve(self, hostname: str, timeout_s: float) -> ResolveResult:
        return ResolveResult(hostname, ProbeOutcome.NO_REPLY, (), None)


def _sentinel_collected() -> Collected:
    """Collected results whose network interface is named ``SENTINEL-IFACE``."""
    return Collected(
        cpu=run_collector(
            "cpu",
            lambda: CpuInfo("cpu", 8, 4, 10.0, 10.0, (10.0,), None, None),
        ),
        memory=run_collector("memory", lambda: MemoryInfo(100, 50, 50, 50.0)),
        storage=run_collector(
            "storage",
            lambda: [VolumeInfo("C:\\", "C:\\", "NTFS", 1000, 100, 900, 87.0)],
        ),
        system=run_collector(
            "system",
            lambda: SystemInfo(
                "host", "Windows", "10", "11", "AMD64",
                "2024-01-01T00:00:00Z", 60,
            ),
        ),
        gpus=run_collector("gpus", list),
        disks=run_collector("disks", list),
        network=run_collector(
            "network",
            lambda: NetworkInfo(
                "SENTINEL-HOST",
                (InterfaceInfo("SENTINEL-IFACE", True, 1000, ("192.168.1.50",), ()),),
                ("fe80::1%12",),
                ("2001:db8::53",),
            ),
        ),
    )


def _result(
    *,
    checks: tuple[Check, ...] = (),
    alerts: tuple[Alert, ...] = (),
    metrics: tuple[Metric, ...] = (),
    status: HealthStatus = HealthStatus.HEALTHY,
    network: NetworkStatus = NetworkStatus.HEALTHY,
) -> DiagnosticResult:
    now = to_iso(utc_now())
    return DiagnosticResult(
        run_id=new_uuid7(),
        device_id="demo-device-0001",
        started_at=now,
        finished_at=now,
        source=RunSource.LIVE,
        status=status,
        network_status=network,
        checks=checks,
        alerts=alerts,
        metrics=metrics,
        facts={},
    )


def test_scrub_ips_redacts_literals_keeps_safe_strings() -> None:
    assert scrub_ips("addr 192.168.0.10 up") == "addr <ip> up"
    assert scrub_ips("gw fe80::1%12") == "gw <ip>"
    assert scrub_ips("dns 2001:db8::53") == "dns <ip>"
    # Safe strings must survive untouched.
    assert scrub_ips("time 16:42:03") == "time 16:42:03"
    assert scrub_ips("C:\\ at 87.0%") == "C:\\ at 87.0%"


def test_sentinel_no_network_identifiers_leak() -> None:
    """A.5 #25 / M3: no interface name, DNS, gateway or IP leaves the host.

    The guarantee is twofold: the rules refer to interfaces by count only
    (structural), and the serializer scrubs any IP literal that still appears in
    evidence. A ``C:\\``/``87.0%`` summary and an ``HH:MM:SS`` time must survive.
    """
    settings = load_settings(env={})
    collected = _sentinel_collected()
    diagnosis = diagnose(collected, _OfflineProber(), settings)
    result = evaluate_result(
        device_id="demo-device-0001",
        collected=collected,
        diagnosis=diagnosis,
        settings=settings,
        source=RunSource.LIVE,
        now=utc_now,
    )
    rendered = json.dumps(build_event(result))

    for forbidden in (
        "SENTINEL-IFACE",
        "SENTINEL-HOST",
        "fe80::1",
        "2001:db8::53",
        "192.168.1.50",
    ):
        assert forbidden not in rendered, f"{forbidden} leaked into telemetry"

    # The disk-usage evidence proves a drive letter and percent survive.
    assert "C:" in rendered
    assert "87.0%" in rendered


def test_scrubber_sentinel_direct_evidence() -> None:
    """Even if an IP reached evidence, the serializer redacts it (defense)."""
    now = to_iso(utc_now())
    check = Check(
        name="network.probe",
        status=CheckStatus.FAIL,
        summary="dns 2001:db8::53 at 16:42:03",
        evidence=("gateway fe80::1%12", "peer 192.168.1.50", "C:\\ at 87.0%"),
        checked_at=now,
    )
    rendered = json.dumps(build_event(_result(checks=(check,))))
    for forbidden in ("fe80::1", "2001:db8::53", "192.168.1.50"):
        assert forbidden not in rendered
    assert "16:42:03" in rendered
    assert "87.0%" in rendered


def test_build_event_passes_validate_event() -> None:
    metric = Metric("network.latency_avg_ms", 12.5, "milliseconds")
    result = _result(metrics=(metric,))
    event = build_event(result)
    code, issues = validate_event(event)
    assert code is None, issues
    # The model's "milliseconds" unit is mapped to the contract unit "ms".
    assert event["metrics"][0]["unit"] == "ms"


def test_offline_and_unknown_omit_none_metrics_and_validate() -> None:
    for status, network in (
        (HealthStatus.UNKNOWN, NetworkStatus.OFFLINE),
        (HealthStatus.UNKNOWN, NetworkStatus.UNKNOWN),
    ):
        result = _result(status=status, network=network, metrics=())
        event = build_event(result)
        assert event["metrics"] == []
        code, issues = validate_event(event)
        assert code is None, issues


def test_build_event_scrubs_alert_message_and_subject() -> None:
    alert = Alert(
        rule_id="NET_DOWN",
        severity=Severity.CRITICAL,
        message="link 10.0.0.5 lost",
        subject="10.0.0.5",
        recommendation="check cable",
    )
    event = build_event(_result(alerts=(alert,)))
    assert "10.0.0.5" not in json.dumps(event)
    assert event["alerts"][0]["message"] == "link <ip> lost"


def test_build_registration_fallbacks_and_validates() -> None:
    facts = {
        "cpu": {"model": "Test CPU", "logical_cpus": 8, "physical_cores": 4},
        "system": {
            "os_name": "Windows",
            "os_version": "10.0.22631",
            "architecture": "AMD64",
        },
        "memory": {"total_bytes": 17179869184},
    }
    payload = build_registration("demo-device-0001", "DEMO-PC", facts)
    assert validate_device_registration(payload) == []
    assert payload["hardware"]["cpu_model"] == "Test CPU"


def test_build_registration_partial_facts_uses_null_and_defaults() -> None:
    payload = build_registration("demo-device-0001", "DEMO-PC", {"cpu": {}})
    assert payload["hardware"]["cpu_model"] is None
    assert payload["hardware"]["physical_cores"] is None
    assert payload["hardware"]["logical_cpus"] >= 1
    assert validate_device_registration(payload) == []
