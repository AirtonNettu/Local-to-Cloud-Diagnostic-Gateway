"""Tests for the deterministic health rules and the evaluator (design B.7)."""

from __future__ import annotations

from agent.collectors.base import CollectorResult, CollectorStatus
from agent.collectors.cpu import CpuInfo
from agent.collectors.hardware import PhysicalDiskInfo
from agent.collectors.memory import MemoryInfo
from agent.collectors.storage import VolumeInfo
from agent.config.settings import Thresholds
from agent.diagnostics.health import HealthEvaluator
from agent.diagnostics.network_diagnostics import NetworkDiagnosis
from agent.diagnostics.rules import (
    DiagnosticInput,
    disk_health,
    internet_connectivity_failure,
    local_network_failure,
    memory_pressure,
    storage_usage,
)
from shared.models.diagnostic import CheckStatus, HealthStatus, NetworkStatus, Severity

_T = Thresholds()


def _ok(data: object) -> CollectorResult:
    return CollectorResult("x", CollectorStatus.OK, data, (), 1)


def _unavailable() -> CollectorResult:
    return CollectorResult("x", CollectorStatus.UNAVAILABLE, None, (), 1)


def _diag(
    *,
    status: NetworkStatus = NetworkStatus.HEALTHY,
    internet: bool = True,
    gateway_reachable: bool | None = True,
    gateways_known: bool | None = True,
    usable: int | None = 1,
    dns: str = "OK",
    latency: float | None = 20.0,
    loss: float | None = 0.0,
) -> NetworkDiagnosis:
    return NetworkDiagnosis(
        local_network_available=True,
        usable_interface_count=usable,
        gateway_reachable=gateway_reachable,
        gateways_known=gateways_known,
        internet_available=internet,
        packet_loss_percent=loss,
        latency_avg_ms=latency,
        latency_min_ms=latency,
        latency_max_ms=latency,
        dns_state=dns,  # type: ignore[arg-type]
        status=status,
        evidence=(),
        possible_causes=(),
        probes=(),
        resolutions=(),
    )


def _volume(percent: float, mount: str = "C:\\") -> VolumeInfo:
    return VolumeInfo(mount, mount, "NTFS", 1000, 100, 900, percent)


def _input(**overrides: object) -> DiagnosticInput:
    base: dict[str, object] = {
        "cpu": _ok(
            CpuInfo("cpu", 8, 4, 10.0, 10.0, (10.0,), None, None)
        ),
        "memory": _ok(MemoryInfo(100, 50, 50, 50.0)),
        "storage": _ok([_volume(10.0)]),
        "disks": _unavailable(),
        "system": _unavailable(),
        "gpus": _unavailable(),
        "network": _unavailable(),
        "diagnosis": _diag(),
        "checked_at": "2024-01-02T03:04:05.678Z",
    }
    base.update(overrides)
    return DiagnosticInput(**base)  # type: ignore[arg-type]


# --- storage.usage: single check, worst status, per-volume alerts ---------


def test_storage_usage_single_check_worst_status() -> None:
    data = _input(storage=_ok([_volume(50.0, "C:\\"), _volume(96.0, "E:\\")]))
    outcome = storage_usage(data, _T)
    assert outcome.check.name == "storage.usage"
    assert outcome.check.status is CheckStatus.FAIL  # one volume critical
    # One alert per offending volume (only E: offends here).
    assert len(outcome.alerts) == 1
    assert outcome.alerts[0].subject == "E:\\"


def test_storage_usage_warning_boundary() -> None:
    below = storage_usage(_input(storage=_ok([_volume(84.9)])), _T)
    assert below.check.status is CheckStatus.PASS
    at = storage_usage(_input(storage=_ok([_volume(85.0)])), _T)
    assert at.check.status is CheckStatus.WARN


def test_storage_usage_critical_boundary() -> None:
    below = storage_usage(_input(storage=_ok([_volume(94.9)])), _T)
    assert below.check.status is CheckStatus.WARN
    at = storage_usage(_input(storage=_ok([_volume(95.0)])), _T)
    assert at.check.status is CheckStatus.FAIL


def test_storage_usage_skipped_when_unavailable() -> None:
    outcome = storage_usage(_input(storage=_unavailable()), _T)
    assert outcome.check.status is CheckStatus.SKIPPED


# --- disk health: subject is disk{index}, no model name -------------------


def test_disk_health_uses_position_not_model() -> None:
    disks = [
        PhysicalDiskInfo("SECRET-MODEL-A", "SSD", "SATA", "Healthy", "OK", 1),
        PhysicalDiskInfo("SECRET-MODEL-B", "SSD", "NVMe", "Warning", "OK", 1),
    ]
    outcome = disk_health(_input(disks=_ok(disks)), _T)
    assert outcome.check.status is CheckStatus.WARN
    assert len(outcome.alerts) == 1
    assert outcome.alerts[0].subject == "disk1"
    # The model string never appears in check or alert text.
    blob = outcome.check.summary + " ".join(outcome.check.evidence)
    blob += outcome.alerts[0].message
    assert "SECRET-MODEL" not in blob


# --- memory boundary ------------------------------------------------------


def test_memory_pressure_boundary() -> None:
    below = memory_pressure(_input(memory=_ok(MemoryInfo(100, 10, 90, 89.9))), _T)
    assert below.check.status is CheckStatus.PASS
    at = memory_pressure(_input(memory=_ok(MemoryInfo(100, 10, 90, 90.0))), _T)
    assert at.check.status is CheckStatus.WARN


# --- connectivity: mutually exclusive -------------------------------------


def test_local_network_failure_when_gateway_down() -> None:
    diag = _diag(
        status=NetworkStatus.OFFLINE,
        internet=False,
        gateway_reachable=False,
    )
    gw = local_network_failure(_input(diagnosis=diag), _T)
    net = internet_connectivity_failure(_input(diagnosis=diag), _T)
    assert gw.check.status is CheckStatus.FAIL
    assert gw.alerts[0].severity is Severity.CRITICAL
    # Internet rule yields to the local failure (mutually exclusive).
    assert net.check.status is CheckStatus.SKIPPED


def test_internet_failure_when_gateway_ok() -> None:
    diag = _diag(
        status=NetworkStatus.OFFLINE,
        internet=False,
        gateway_reachable=True,
    )
    gw = local_network_failure(_input(diagnosis=diag), _T)
    net = internet_connectivity_failure(_input(diagnosis=diag), _T)
    assert gw.check.status is CheckStatus.PASS
    assert net.check.status is CheckStatus.FAIL
    assert net.alerts[0].severity is Severity.WARNING


def test_internet_failure_when_gateway_unknown() -> None:
    # Ping ERROR -> gateway unknown; internet down -> INTERNET_CONNECTIVITY_FAILURE
    # with "gateway status unknown", never LOCAL_NETWORK_FAILURE.
    diag = _diag(
        status=NetworkStatus.OFFLINE,
        internet=False,
        gateway_reachable=None,
        gateways_known=True,
    )
    gw = local_network_failure(_input(diagnosis=diag), _T)
    net = internet_connectivity_failure(_input(diagnosis=diag), _T)
    assert gw.check.status is CheckStatus.SKIPPED
    assert net.check.status is CheckStatus.FAIL
    assert "gateway status unknown" in net.check.evidence


def test_both_connectivity_skipped_when_unknown() -> None:
    diag = _diag(status=NetworkStatus.UNKNOWN, internet=False)
    gw = local_network_failure(_input(diagnosis=diag), _T)
    net = internet_connectivity_failure(_input(diagnosis=diag), _T)
    assert gw.check.status is CheckStatus.SKIPPED
    assert net.check.status is CheckStatus.SKIPPED


# --- evaluator: overall status + check-name uniqueness --------------------


def test_evaluator_check_names_unique() -> None:
    evaluation = HealthEvaluator().evaluate(_input(), _T)
    names = [c.name for c in evaluation.checks]
    assert len(names) == len(set(names))


def test_evaluator_overall_healthy() -> None:
    evaluation = HealthEvaluator().evaluate(_input(), _T)
    assert evaluation.status is HealthStatus.HEALTHY


def test_evaluator_overall_critical_on_critical_alert() -> None:
    diag = _diag(
        status=NetworkStatus.OFFLINE, internet=False, gateway_reachable=False
    )
    evaluation = HealthEvaluator().evaluate(_input(diagnosis=diag), _T)
    assert evaluation.status is HealthStatus.CRITICAL


def test_evaluator_unknown_when_core_collectors_failed() -> None:
    failed = CollectorResult("x", CollectorStatus.FAILED, None, ("e",), 1)
    data = _input(cpu=failed, memory=failed, storage=failed)
    evaluation = HealthEvaluator().evaluate(data, _T)
    # A COLLECTOR_FAILURE INFO alert never changes status away from UNKNOWN.
    assert evaluation.status is HealthStatus.UNKNOWN
