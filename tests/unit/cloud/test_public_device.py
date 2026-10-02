"""to_public()/diagnostic_to_public() never leak internal attributes."""

from __future__ import annotations

import json
from decimal import Decimal

from cloud.repository import diagnostic_to_public, to_public

_FORBIDDEN = {"PK", "SK", "GSI1PK", "GSI1SK", "entity", "payload_sha256", "payload"}


def _stored_profile() -> dict:
    return {
        "PK": "DEVICE#d1",
        "SK": "PROFILE",
        "GSI1PK": "DEVICE",
        "GSI1SK": "DEVICE#d1",
        "entity": "device",
        "payload_sha256": "deadbeef",
        "device_id": "d1",
        "device_name": "PC-001",
        "os": {"name": "Windows", "version": "10", "architecture": "AMD64"},
        "hardware": {
            "logical_cpus": Decimal(12),
            "memory_total_bytes": Decimal(17179869184),
        },
        "agent_version": "0.1.0",
        "registered_at": "2026-01-10T16:40:00.000Z",
        "updated_at": "2026-01-10T16:40:00.000Z",
        "last_seen_at": "2026-01-10T16:42:03.500Z",
        "latest_event_id": "01923c5e-7b8a-7c3d-9e21-4f5a6b7c8d9e",
        "latest_status": "DEGRADED",
        "latest_network_status": "HEALTHY",
        "latest_event_at": "2026-01-10T16:42:03.120Z",
    }


def test_public_device_hides_internal_keys() -> None:
    public = to_public(_stored_profile())
    assert _FORBIDDEN.isdisjoint(public.keys())


def test_public_device_decimals_become_int() -> None:
    public = to_public(_stored_profile())
    assert public["hardware"]["logical_cpus"] == 12
    assert isinstance(public["hardware"]["logical_cpus"], int)
    # Serializable without Decimal errors.
    json.dumps(public)


def test_public_device_latest_block() -> None:
    public = to_public(_stored_profile())
    assert public["latest"]["status"] == "DEGRADED"
    assert public["latest"]["event_id"].startswith("01923c5e")


def test_public_device_latest_null_before_telemetry() -> None:
    profile = _stored_profile()
    for key in (
        "latest_event_id",
        "latest_status",
        "latest_network_status",
        "latest_event_at",
        "last_seen_at",
    ):
        profile.pop(key)
    public = to_public(profile)
    assert public["latest"] is None
    assert public["last_seen_at"] is None


def test_diagnostic_public_hides_internal_keys() -> None:
    item = {
        "PK": "DEVICE#d1",
        "SK": "DIAG#01923c5e",
        "entity": "diagnostic",
        "payload_sha256": "abc",
        "event_id": "01923c5e-7b8a-7c3d-9e21-4f5a6b7c8d9e",
        "timestamp": "2026-01-10T16:42:03.120Z",
        "received_at": "2026-01-10T16:42:03.500Z",
        "source": "live",
        "status": "DEGRADED",
        "network_status": "HEALTHY",
        "alert_count": Decimal(1),
        "payload": json.dumps(
            {"checks": [{"name": "storage.usage"}], "alerts": [], "metrics": []}
        ),
    }
    public = diagnostic_to_public(item)
    assert _FORBIDDEN.isdisjoint(public.keys())
    assert public["alert_count"] == 1
    assert public["checks"] == [{"name": "storage.usage"}]
