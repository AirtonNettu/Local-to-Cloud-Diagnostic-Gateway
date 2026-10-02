"""Tests for the shared diagnostic and device models."""

from __future__ import annotations

from shared.models.device import DeviceInfo
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


def _sample_result() -> DiagnosticResult:
    return DiagnosticResult(
        run_id="018f0000-0000-7000-8000-000000000000",
        device_id="dev-1",
        started_at="2024-01-02T03:04:05.000Z",
        finished_at="2024-01-02T03:04:06.000Z",
        source=RunSource.LIVE,
        status=HealthStatus.HEALTHY,
        network_status=NetworkStatus.HEALTHY,
        checks=(
            Check(
                name="cpu.usage",
                status=CheckStatus.PASS,
                summary="CPU usage normal",
                evidence=("avg 12%",),
                checked_at="2024-01-02T03:04:05.500Z",
            ),
        ),
        alerts=(
            Alert(
                rule_id="HIGH_CPU_USAGE",
                severity=Severity.WARNING,
                message="CPU high",
                subject=None,
                recommendation="Check busy processes.",
            ),
        ),
        metrics=(Metric(name="cpu.usage_percent", value=12.3, unit="percent"),),
        facts={"cpu": {"model": "Demo CPU"}},
    )


def test_enum_values_serialize_as_strings() -> None:
    assert RunSource.LIVE.value == "live"
    assert HealthStatus.CRITICAL.value == "CRITICAL"
    assert CheckStatus.SKIPPED.value == "SKIPPED"


def test_diagnostic_result_round_trip() -> None:
    original = _sample_result()
    restored = DiagnosticResult.from_dict(original.to_dict())
    assert restored == original


def test_metric_defaults_empty_labels() -> None:
    metric = Metric(name="m", value=1.0, unit="count")
    assert metric.labels == {}
    assert metric.to_dict()["labels"] == {}


def test_device_info_round_trip() -> None:
    info = DeviceInfo(
        device_id="dev-1",
        device_name="Workstation",
        os_name="Windows",
        os_version="10.0.22631",
        agent_version="0.1.0",
    )
    assert DeviceInfo.from_dict(info.to_dict()) == info


def test_frozen_dataclasses_are_immutable() -> None:
    check = _sample_result().checks[0]
    try:
        check.name = "other"  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("Check should be frozen")
