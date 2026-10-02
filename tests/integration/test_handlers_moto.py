"""Integration tests for the Lambda handlers under moto (design B.20).

Each handler is invoked with a real HTTP API v2 event against a moto-backed
DynamoDB table and SSM SecureString keys, so the full ingest/read path runs
locally with no AWS account involved. The handler modules cache settings, the
auth provider and the table resource in module globals; the autouse fixture
resets them and the ``get_table`` cache so every test starts clean.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from moto import mock_aws

from cloud import repository
from cloud.handlers import device, diagnostic, health, telemetry
from shared.utils.ids import new_uuid7
from shared.utils.timeutil import to_iso, utc_now

TABLE_NAME = "diagnostics-test"
INGEST_PARAM = "/diagnostic-gateway/test/ingest-api-key"
READ_PARAM = "/diagnostic-gateway/test/read-api-key"
INGEST_KEY = "ingest-" + "a" * 40
READ_KEY = "read-" + "b" * 40

DEVICE_ID = "test-device-0001"


@pytest.fixture(autouse=True)
def cloud_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Set handler env, create the moto table + SSM keys, reset caches."""
    monkeypatch.setenv("TABLE_NAME", TABLE_NAME)
    monkeypatch.setenv("INGEST_KEY_PARAMETER", INGEST_PARAM)
    monkeypatch.setenv("READ_KEY_PARAMETER", READ_PARAM)
    monkeypatch.setenv("DIAGNOSTIC_RETENTION_DAYS", "30")

    with mock_aws():
        _create_table()
        _put_keys()
        _reset_handler_state()
        repository.get_table.cache_clear()
        yield
        repository.get_table.cache_clear()
        _reset_handler_state()


def _create_table() -> None:
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName=TABLE_NAME,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI1PK", "AttributeType": "S"},
            {"AttributeName": "GSI1SK", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": repository.GSI1_NAME,
                "KeySchema": [
                    {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    )


def _put_keys() -> None:
    ssm = boto3.client("ssm", region_name="us-east-1")
    ssm.put_parameter(Name=INGEST_PARAM, Value=INGEST_KEY, Type="SecureString")
    ssm.put_parameter(Name=READ_PARAM, Value=READ_KEY, Type="SecureString")


def _reset_handler_state() -> None:
    for module in (device, diagnostic, telemetry):
        module._settings = None  # type: ignore[attr-defined]
        module._auth = None  # type: ignore[attr-defined]


# --- event helpers -----------------------------------------------------------


def _event(
    method: str,
    path: str,
    *,
    route_key: str,
    body: Any = None,
    key: str | None = None,
    path_params: dict[str, str] | None = None,
    query: dict[str, str] | None = None,
) -> dict[str, Any]:
    headers: dict[str, str] = {}
    if key is not None:
        headers["authorization"] = f"Bearer {key}"
    return {
        "version": "2.0",
        "routeKey": route_key,
        "rawPath": path,
        "headers": headers,
        "queryStringParameters": query or {},
        "pathParameters": path_params or {},
        "body": json.dumps(body) if body is not None else None,
        "isBase64Encoded": False,
        "requestContext": {
            "requestId": "req-123",
            "http": {"method": method, "path": path},
        },
    }


def _body(response: dict[str, Any]) -> dict[str, Any]:
    return json.loads(response["body"])


def _registration(device_id: str = DEVICE_ID) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "device_id": device_id,
        "device_name": "Test PC",
        "os": {"name": "Windows", "version": "10.0.22631", "architecture": "AMD64"},
        "hardware": {
            "cpu_model": "Test CPU",
            "logical_cpus": 4,
            "physical_cores": 4,
            "memory_total_bytes": 16 * 1024**3,
        },
        "agent_version": "0.1.0",
    }


def _event_payload(
    event_id: str, *, status: str = "HEALTHY", network: str = "HEALTHY"
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "event_type": "diagnostic_run",
        "schema_version": 1,
        "timestamp": to_iso(utc_now()),
        "source": "live",
        "status": status,
        "network_status": network,
        "checks": [],
        "alerts": [],
        "metrics": [],
    }


def _register(device_id: str = DEVICE_ID) -> dict[str, Any]:
    return device.handler(
        _event(
            "POST",
            "/v1/devices",
            route_key="POST /v1/devices",
            body=_registration(device_id),
            key=INGEST_KEY,
        )
    )


def _telemetry(
    events: list[dict[str, Any]], device_id: str = DEVICE_ID
) -> dict[str, Any]:
    return telemetry.handler(
        _event(
            "POST",
            "/v1/telemetry",
            route_key="POST /v1/telemetry",
            body={"schema_version": 1, "device_id": device_id, "events": events},
            key=INGEST_KEY,
        )
    )


# --- registration ------------------------------------------------------------


def test_register_returns_201_then_200() -> None:
    first = _register()
    assert first["statusCode"] == 201
    assert _body(first)["created"] is True

    second = _register()
    assert second["statusCode"] == 200
    assert _body(second)["created"] is False


# --- telemetry ---------------------------------------------------------------


def test_telemetry_accepted_then_duplicate() -> None:
    _register()
    event = _event_payload(new_uuid7())
    first = _telemetry([event])
    assert first["statusCode"] == 200
    assert _body(first)["results"][0]["status"] == "accepted"

    second = _telemetry([event])
    assert _body(second)["results"][0]["status"] == "duplicate"


def test_telemetry_event_id_conflict() -> None:
    _register()
    event_id = new_uuid7()
    _telemetry([_event_payload(event_id, status="HEALTHY")])
    conflict = _telemetry([_event_payload(event_id, status="CRITICAL")])
    item = _body(conflict)["results"][0]
    assert item["status"] == "rejected"
    assert item["error"]["code"] == "EVENT_ID_CONFLICT"


def test_telemetry_mixed_valid_and_invalid_batch() -> None:
    _register()
    good = _event_payload(new_uuid7())
    bad = _event_payload(new_uuid7())
    del bad["status"]  # schema violation
    response = _telemetry([good, bad])
    assert response["statusCode"] == 200
    body = _body(response)
    statuses = {r["event_id"]: r["status"] for r in body["results"]}
    assert statuses[good["event_id"]] == "accepted"
    assert statuses[bad["event_id"]] == "rejected"
    assert body["accepted"] == 1
    assert body["rejected"] == 1


def test_telemetry_unregistered_device_409() -> None:
    response = _telemetry([_event_payload(new_uuid7())], device_id="ghost-device-1")
    assert response["statusCode"] == 409
    assert _body(response)["error"]["code"] == "DEVICE_NOT_REGISTERED"


def test_telemetry_body_over_limit_413() -> None:
    _register()
    # One event padded past MAX_REQUEST_BYTES via a huge evidence string.
    event = _event_payload(new_uuid7())
    event["checks"] = [
        {
            "name": "pad.check",
            "status": "PASS",
            "summary": "x",
            "evidence": ["y" * 300_000],
        }
    ]
    response = _telemetry([event])
    assert response["statusCode"] == 413
    assert _body(response)["error"]["code"] == "PAYLOAD_TOO_LARGE"


# --- device read -------------------------------------------------------------


def test_list_devices_with_pagination() -> None:
    for i in range(3):
        _register(device_id=f"test-device-{i:04d}")
    response = device.handler(
        _event(
            "GET",
            "/v1/devices",
            route_key="GET /v1/devices",
            key=READ_KEY,
            query={"limit": "2"},
        )
    )
    assert response["statusCode"] == 200
    body = _body(response)
    assert len(body["items"]) == 2
    assert body["next_cursor"] is not None

    page2 = device.handler(
        _event(
            "GET",
            "/v1/devices",
            route_key="GET /v1/devices",
            key=READ_KEY,
            query={"limit": "2", "cursor": body["next_cursor"]},
        )
    )
    assert page2["statusCode"] == 200
    assert len(_body(page2)["items"]) == 1


def test_diagnostics_newest_first() -> None:
    _register()
    ids = [new_uuid7() for _ in range(3)]
    for event_id in ids:
        _telemetry([_event_payload(event_id)])
    response = diagnostic.handler(
        _event(
            "GET",
            f"/v1/devices/{DEVICE_ID}/diagnostics",
            route_key="GET /v1/devices/{device_id}/diagnostics",
            key=READ_KEY,
            path_params={"device_id": DEVICE_ID},
        )
    )
    assert response["statusCode"] == 200
    returned = [item["event_id"] for item in _body(response)["items"]]
    assert returned == sorted(ids, reverse=True)


# --- auth --------------------------------------------------------------------


def test_missing_key_is_401() -> None:
    response = device.handler(
        _event("GET", "/v1/devices", route_key="GET /v1/devices")
    )
    assert response["statusCode"] == 401


def test_wrong_scope_is_403() -> None:
    # The read key cannot register (ingest scope).
    response = device.handler(
        _event(
            "POST",
            "/v1/devices",
            route_key="POST /v1/devices",
            body=_registration(),
            key=READ_KEY,
        )
    )
    assert response["statusCode"] == 403


# --- dependency failures (503 / 500) -----------------------------------------


def test_throttling_maps_to_503(monkeypatch: pytest.MonkeyPatch) -> None:
    _register()
    from botocore.exceptions import ClientError

    def _throttle(*_: object, **__: object) -> None:
        raise ClientError(
            {"Error": {"Code": "ProvisionedThroughputExceededException"}},
            "GetItem",
        )

    monkeypatch.setattr(repository.DeviceRepository, "get", _throttle)
    response = _telemetry([_event_payload(new_uuid7())])
    assert response["statusCode"] == 503
    assert _body(response)["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_injected_exception_is_500_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _register()

    def _boom(*_: object, **__: object) -> None:
        raise RuntimeError("secret-internal-detail")

    monkeypatch.setattr(repository.DeviceRepository, "get", _boom)
    response = _telemetry([_event_payload(new_uuid7())])
    assert response["statusCode"] == 500
    body = response["body"]
    assert "secret-internal-detail" not in body
    assert "Traceback" not in body
    assert _body(response)["error"]["code"] == "INTERNAL_ERROR"


def test_503_mid_batch_then_retry_advances_last_seen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient error mid-batch aborts 503; the retry stores + advances AP6."""
    _register()
    from botocore.exceptions import ClientError

    events = [_event_payload(new_uuid7()) for _ in range(2)]

    original = repository.DiagnosticRepository.put_event
    calls = {"n": 0}

    def _flaky(self: Any, item: dict[str, Any], *, event_sha: str) -> Any:
        calls["n"] += 1
        if calls["n"] == 2:
            raise ClientError(
                {"Error": {"Code": "ThrottlingException"}}, "PutItem"
            )
        return original(self, item, event_sha=event_sha)

    monkeypatch.setattr(repository.DiagnosticRepository, "put_event", _flaky)
    aborted = _telemetry(events)
    assert aborted["statusCode"] == 503

    # Retry without the fault: first event is a duplicate, second is accepted.
    monkeypatch.setattr(repository.DiagnosticRepository, "put_event", original)
    retried = _telemetry(events)
    assert retried["statusCode"] == 200

    get_response = device.handler(
        _event(
            "GET",
            f"/v1/devices/{DEVICE_ID}",
            route_key="GET /v1/devices/{device_id}",
            key=READ_KEY,
            path_params={"device_id": DEVICE_ID},
        )
    )
    assert get_response["statusCode"] == 200
    assert _body(get_response)["last_seen_at"] is not None


# --- health (no auth, no AWS) ------------------------------------------------


def test_health_ok_without_auth() -> None:
    response = health.handler(
        _event("GET", "/health", route_key="GET /health")
    )
    assert response["statusCode"] == 200
    assert _body(response)["status"] == "ok"
