"""Shared validator tests: device registration and telemetry (§B.11)."""

from __future__ import annotations

from datetime import timedelta

from shared.schemas.common import MAX_CLOCK_SKEW_SECONDS
from shared.schemas.device import validate_device_registration
from shared.schemas.telemetry import validate_event, validate_telemetry_envelope
from shared.utils.ids import new_uuid7
from shared.utils.timeutil import to_iso, utc_now


def _valid_registration() -> dict:
    return {
        "schema_version": 1,
        "device_id": "demo-device-0001",
        "device_name": "DEMO-PC",
        "os": {"name": "Windows", "version": "10.0.22631", "architecture": "AMD64"},
        "hardware": {
            "cpu_model": "Test CPU",
            "logical_cpus": 12,
            "physical_cores": 10,
            "memory_total_bytes": 17179869184,
        },
        "agent_version": "0.1.0",
    }


def _valid_event(timestamp: str | None = None) -> dict:
    return {
        "event_id": new_uuid7(),
        "event_type": "diagnostic_run",
        "schema_version": 1,
        "timestamp": timestamp or to_iso(utc_now()),
        "source": "live",
        "status": "DEGRADED",
        "network_status": "HEALTHY",
        "checks": [
            {
                "name": "storage.usage",
                "status": "WARN",
                "summary": "C:\\ at 87.0%",
                "evidence": ["C:\\ 87.0% used"],
            }
        ],
        "alerts": [
            {
                "rule_id": "DISK_SPACE_WARNING",
                "severity": "WARNING",
                "message": "Volume usage high",
                "subject": "C:\\",
            }
        ],
        "metrics": [
            {
                "name": "storage.usage_percent",
                "value": 87.0,
                "unit": "percent",
                "labels": {"volume": "C"},
            }
        ],
    }


# --- registration ------------------------------------------------------------
def test_valid_registration_passes() -> None:
    assert validate_device_registration(_valid_registration()) == []


def test_registration_rejects_unknown_field() -> None:
    payload = _valid_registration()
    payload["extra"] = 1
    issues = validate_device_registration(payload)
    assert any(i.field == "extra" for i in issues)


def test_registration_bad_version_and_bad_memory() -> None:
    payload = _valid_registration()
    payload["agent_version"] = "not-a-version"
    payload["hardware"]["memory_total_bytes"] = 0
    issues = validate_device_registration(payload)
    fields = {i.field for i in issues}
    assert "agent_version" in fields
    assert "hardware.memory_total_bytes" in fields


def test_registration_cpu_model_and_cores_may_be_null() -> None:
    payload = _valid_registration()
    payload["hardware"]["cpu_model"] = None
    payload["hardware"]["physical_cores"] = None
    assert validate_device_registration(payload) == []


# --- telemetry envelope ------------------------------------------------------
def test_envelope_valid() -> None:
    envelope = {
        "schema_version": 1,
        "device_id": "demo-device-0001",
        "events": [_valid_event()],
    }
    assert validate_telemetry_envelope(envelope) == []


def test_envelope_rejects_empty_events() -> None:
    envelope = {"schema_version": 1, "device_id": "demo-device-0001", "events": []}
    issues = validate_telemetry_envelope(envelope)
    assert any(i.field == "events" for i in issues)


def test_envelope_rejects_too_many_events() -> None:
    envelope = {
        "schema_version": 1,
        "device_id": "demo-device-0001",
        "events": [_valid_event() for _ in range(11)],
    }
    assert any(i.field == "events" for i in validate_telemetry_envelope(envelope))


# --- per-event ---------------------------------------------------------------
def test_event_valid() -> None:
    code, issues = validate_event(_valid_event())
    assert code is None, issues


def test_event_bool_as_metric_value_rejected() -> None:
    event = _valid_event()
    event["metrics"][0]["value"] = True
    code, issues = validate_event(event)
    assert code == "VALIDATION_ERROR"
    assert any("value" in i.field for i in issues)


def test_event_unknown_field_rejected() -> None:
    event = _valid_event()
    event["surprise"] = 1
    code, issues = validate_event(event)
    assert code == "VALIDATION_ERROR"
    assert any(i.field == "surprise" for i in issues)


def test_future_timestamp_is_clock_skew_even_with_other_invalid_fields() -> None:
    far_future = to_iso(utc_now() + timedelta(seconds=MAX_CLOCK_SKEW_SECONDS + 60))
    event = _valid_event(timestamp=far_future)
    event["status"] = "NOT_A_STATUS"  # also invalid
    code, issues = validate_event(event)
    assert code == "CLOCK_SKEW"
    assert all(i.field == "timestamp" for i in issues)


def test_timestamp_299s_ahead_accepted() -> None:
    near_future = to_iso(utc_now() + timedelta(seconds=MAX_CLOCK_SKEW_SECONDS - 1))
    code, issues = validate_event(_valid_event(timestamp=near_future))
    assert code is None, issues


def test_bad_metric_unit_rejected() -> None:
    event = _valid_event()
    event["metrics"][0]["unit"] = "milliseconds"  # not in the contract set
    code, issues = validate_event(event)
    assert code == "VALIDATION_ERROR"
    assert any("unit" in i.field for i in issues)
