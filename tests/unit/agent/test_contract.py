"""Contract tests: agent output is always acceptable to the backend.

The agent pre-checks every outgoing payload with the same shared validator the
cloud enforces, so these tests prove the serializer can never emit a payload the
cloud would reject. Also asserts ``agent.__version__`` matches the contract
``AGENT_VERSION_PATTERN`` (review NIT9).
"""

from __future__ import annotations

from agent import __version__
from agent.sync.serializer import build_event, build_registration
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
from shared.schemas.common import AGENT_VERSION_PATTERN
from shared.schemas.device import validate_device_registration
from shared.schemas.telemetry import validate_event
from shared.utils.ids import new_uuid7
from shared.utils.timeutil import to_iso, utc_now


def test_agent_version_matches_contract_pattern() -> None:
    assert AGENT_VERSION_PATTERN.match(__version__), __version__


def test_build_registration_is_contract_valid() -> None:
    facts = {
        "cpu": {"model": "CPU", "logical_cpus": 8, "physical_cores": 4},
        "system": {
            "os_name": "Windows",
            "os_version": "10.0.22631",
            "architecture": "AMD64",
        },
        "memory": {"total_bytes": 8589934592},
    }
    payload = build_registration("demo-device-0001", "DEMO-PC", facts)
    assert validate_device_registration(payload) == []


def test_build_event_full_result_is_contract_valid() -> None:
    now = to_iso(utc_now())
    result = DiagnosticResult(
        run_id=new_uuid7(),
        device_id="demo-device-0001",
        started_at=now,
        finished_at=now,
        source=RunSource.LIVE,
        status=HealthStatus.DEGRADED,
        network_status=NetworkStatus.HEALTHY,
        checks=(
            Check(
                name="storage.usage",
                status=CheckStatus.WARN,
                summary="C:\\ at 87.0%",
                evidence=("C:\\ 87.0% used", "peer 10.0.0.1"),
                checked_at=now,
            ),
        ),
        alerts=(
            Alert(
                rule_id="DISK_SPACE_WARNING",
                severity=Severity.WARNING,
                message="Volume C:\\ usage high",
                subject="C:\\",
                recommendation="free space",
            ),
        ),
        metrics=(
            Metric("storage.usage_percent", 87.0, "percent", {"volume": "C"}),
            Metric("network.latency_avg_ms", 12.5, "milliseconds"),
            Metric("system.uptime_seconds", 3600.0, "seconds"),
        ),
        facts={},
    )
    event = build_event(result)
    code, issues = validate_event(event)
    assert code is None, issues
