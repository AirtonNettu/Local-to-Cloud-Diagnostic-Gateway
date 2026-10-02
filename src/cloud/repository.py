"""DynamoDB single-table repository (design B.10).

One table holds device profiles (``SK=PROFILE``) and diagnostic events
(``SK=DIAG#<event_id>``) in the same ``PK=DEVICE#<id>`` partition. The sparse
GSI1 (only profiles carry ``GSI1PK=DEVICE``) answers "list devices". The
``botocore`` client config pins the retry mode and timeouts, and the table
resource is cached with ``lru_cache`` so tests create it under ``moto.mock_aws``
and clear the cache between cases.

``to_public`` is the single mapping from a stored profile to the public device
object; it never returns ``PK``/``SK``/``GSI1*``/``entity``/``payload_sha256``
and converts DynamoDB ``Decimal`` numbers back to ``int`` (asserted by a unit
test). Idempotent ingest uses a conditional ``PutItem`` with
``ReturnValuesOnConditionCheckFailure=ALL_OLD`` and compares ``payload_sha256``
to tell a duplicate (same payload) from an ``EVENT_ID_CONFLICT`` (reused id,
different payload).
"""

from __future__ import annotations

import json
from decimal import Decimal
from enum import Enum
from functools import lru_cache
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

__all__ = [
    "DeviceRepository",
    "DiagnosticRepository",
    "IngestOutcome",
    "payload_sha256",
    "to_public",
    "get_table",
    "GSI1_NAME",
]

GSI1_NAME = "GSI1"
_GSI1_PARTITION = "DEVICE"
_PROFILE_SK = "PROFILE"
_DIAG_PREFIX = "DIAG#"

# Keys never exposed by the public API (asserted by test_public_device.py).
_INTERNAL_KEYS = frozenset(
    {"PK", "SK", "GSI1PK", "GSI1SK", "entity", "payload_sha256", "payload"}
)

_BOTO_CONFIG = Config(
    retries={"mode": "standard", "max_attempts": 3},
    connect_timeout=2,
    read_timeout=5,
)


@lru_cache(maxsize=None)  # noqa: UP033 - cache_clear() is used by tests (B.10)
def get_table(table_name: str) -> Any:
    """Return a cached DynamoDB ``Table`` resource for ``table_name``.

    Cached so a warm Lambda reuses one client; tests clear the cache
    (``get_table.cache_clear()``) after creating the table under ``moto``.
    """
    resource = boto3.resource("dynamodb", config=_BOTO_CONFIG)
    return resource.Table(table_name)


def _device_pk(device_id: str) -> str:
    return f"DEVICE#{device_id}"


def _diag_sk(event_id: str) -> str:
    return f"{_DIAG_PREFIX}{event_id}"


def payload_sha256(payload: dict[str, Any]) -> str:
    """Return the SHA-256 of the canonical JSON of ``payload``.

    Canonical form is ``sort_keys=True`` with compact separators, so two logically
    equal payloads hash identically regardless of key order or whitespace.
    """
    import hashlib

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _decimals_to_int(value: Any) -> Any:
    """Recursively convert DynamoDB ``Decimal`` numbers to ``int``."""
    if isinstance(value, Decimal):
        return int(value)
    if isinstance(value, dict):
        return {k: _decimals_to_int(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decimals_to_int(v) for v in value]
    return value


def to_public(item: dict[str, Any]) -> dict[str, Any]:
    """Map a stored device-profile item to the public device object (B.11).

    Internal attributes are never included. ``last_seen_at`` and ``latest`` are
    ``null`` until the first telemetry is ingested.
    """
    latest_event_id = item.get("latest_event_id")
    latest: dict[str, Any] | None = None
    if latest_event_id is not None:
        latest = {
            "event_id": latest_event_id,
            "status": item.get("latest_status"),
            "network_status": item.get("latest_network_status"),
            "timestamp": item.get("latest_event_at"),
        }
    public: dict[str, Any] = {
        "device_id": item.get("device_id"),
        "device_name": item.get("device_name"),
        "os": item.get("os"),
        "hardware": item.get("hardware"),
        "agent_version": item.get("agent_version"),
        "registered_at": item.get("registered_at"),
        "updated_at": item.get("updated_at"),
        "last_seen_at": item.get("last_seen_at"),
        "latest": latest,
    }
    converted: dict[str, Any] = _decimals_to_int(public)
    return converted


class IngestOutcome(str, Enum):
    """Outcome of a single conditional event write."""

    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"


# --- transient AWS error classification -------------------------------------
_TRANSIENT_DDB_CODES = frozenset(
    {
        "ProvisionedThroughputExceededException",
        "ThrottlingException",
        "RequestLimitExceeded",
        "InternalServerError",
    }
)


def is_transient_client_error(exc: ClientError) -> bool:
    """Return True for the DynamoDB error codes that map to a 503 (B.14)."""
    code = exc.response.get("Error", {}).get("Code", "")
    return code in _TRANSIENT_DDB_CODES


class DeviceRepository:
    """Device-profile reads and the idempotent register/update upsert."""

    def __init__(self, table: Any) -> None:
        self._table = table

    def upsert(self, registration: dict[str, Any], *, now_iso: str) -> bool:
        """AP1: idempotent register/update. Returns True when newly created.

        ``created`` is derived from ``ReturnValues=ALL_OLD`` being empty (no prior
        item). ``registered_at`` is written only on first creation
        (``if_not_exists``); ``updated_at`` always advances.
        """
        device_id = registration["device_id"]
        os_block = registration["os"]
        hardware = dict(registration["hardware"])
        # cpu_model may be null (partial facts); store it as absent.
        if hardware.get("cpu_model") is None:
            hardware.pop("cpu_model", None)

        response = self._table.update_item(
            Key={"PK": _device_pk(device_id), "SK": _PROFILE_SK},
            UpdateExpression=(
                "SET entity = :entity, GSI1PK = :gpk, GSI1SK = :gsk, "
                "device_id = :did, device_name = :dname, os = :os, "
                "hardware = :hw, agent_version = :ver, updated_at = :now, "
                "registered_at = if_not_exists(registered_at, :now)"
            ),
            ExpressionAttributeValues={
                ":entity": "device",
                ":gpk": _GSI1_PARTITION,
                ":gsk": _device_pk(device_id),
                ":did": device_id,
                ":dname": registration["device_name"],
                ":os": os_block,
                ":hw": hardware,
                ":ver": registration["agent_version"],
                ":now": now_iso,
            },
            ReturnValues="ALL_OLD",
        )
        old = response.get("Attributes")
        return not old

    def get(self, device_id: str) -> dict[str, Any] | None:
        """AP2: return the stored profile item, or ``None`` if absent."""
        response = self._table.get_item(
            Key={"PK": _device_pk(device_id), "SK": _PROFILE_SK}
        )
        item = response.get("Item")
        return dict(item) if item else None

    def list_devices(
        self, *, limit: int, start_key: dict[str, Any] | None
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """AP3: list devices via GSI1, paginated. Returns (items, next_key)."""
        from boto3.dynamodb.conditions import Key

        kwargs: dict[str, Any] = {
            "IndexName": GSI1_NAME,
            "KeyConditionExpression": Key("GSI1PK").eq(_GSI1_PARTITION),
            "Limit": limit,
        }
        if start_key is not None:
            kwargs["ExclusiveStartKey"] = start_key
        response = self._table.query(**kwargs)
        items = [dict(i) for i in response.get("Items", [])]
        next_key = response.get("LastEvaluatedKey")
        return items, (dict(next_key) if next_key else None)

    def touch_last_seen(self, device_id: str, *, received_at: str) -> None:
        """AP6b: advance ``last_seen_at`` on any accepted ingest request."""
        try:
            self._table.update_item(
                Key={"PK": _device_pk(device_id), "SK": _PROFILE_SK},
                UpdateExpression="SET last_seen_at = :ts",
                ConditionExpression="attribute_exists(PK)",
                ExpressionAttributeValues={":ts": received_at},
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == (
                "ConditionalCheckFailedException"
            ):
                return  # profile vanished; nothing to touch
            raise

    def update_latest(
        self,
        device_id: str,
        *,
        event_id: str,
        status: str,
        network_status: str,
        event_at: str,
        received_at: str,
    ) -> None:
        """AP6: set latest status for the newest accepted/duplicate event.

        Also advances ``last_seen_at``. The ``latest_event_id < :eid`` guard keeps
        the update idempotent and ``attribute_exists(PK)`` prevents creating a
        headless profile. A ``ConditionalCheckFailed`` means a newer event already
        won, so AP6b runs alone to still advance ``last_seen_at``.
        """
        try:
            self._table.update_item(
                Key={"PK": _device_pk(device_id), "SK": _PROFILE_SK},
                UpdateExpression=(
                    "SET latest_event_id = :eid, latest_status = :st, "
                    "latest_network_status = :net, latest_event_at = :evat, "
                    "last_seen_at = :recv"
                ),
                ConditionExpression=(
                    "attribute_exists(PK) AND "
                    "(attribute_not_exists(latest_event_id) OR "
                    "latest_event_id < :eid)"
                ),
                ExpressionAttributeValues={
                    ":eid": event_id,
                    ":st": status,
                    ":net": network_status,
                    ":evat": event_at,
                    ":recv": received_at,
                },
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == (
                "ConditionalCheckFailedException"
            ):
                self.touch_last_seen(device_id, received_at=received_at)
                return
            raise


class DiagnosticRepository:
    """Diagnostic-event writes (idempotent) and newest-first reads."""

    def __init__(self, table: Any) -> None:
        self._table = table

    def put_event(
        self, item: dict[str, Any], *, event_sha: str
    ) -> IngestOutcome:
        """AP4: conditional put for exactly-once ingest.

        Returns ``ACCEPTED`` for a new item, ``DUPLICATE`` when the same
        ``event_id`` already stores the same payload hash, or ``CONFLICT`` when
        the hash differs (``event_id`` reuse with a different payload).
        """
        try:
            self._table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(PK)",
                ReturnValuesOnConditionCheckFailure="ALL_OLD",
            )
            return IngestOutcome.ACCEPTED
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != (
                "ConditionalCheckFailedException"
            ):
                raise
            stored = exc.response.get("Item", {})
            existing_sha = _stored_scalar(stored, "payload_sha256")
            if existing_sha == event_sha:
                return IngestOutcome.DUPLICATE
            return IngestOutcome.CONFLICT

    def query_recent(
        self, device_id: str, *, limit: int, start_key: dict[str, Any] | None
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """AP5: diagnostics for a device, newest first. Returns (items, next)."""
        from boto3.dynamodb.conditions import Key

        kwargs: dict[str, Any] = {
            "KeyConditionExpression": (
                Key("PK").eq(_device_pk(device_id))
                & Key("SK").begins_with(_DIAG_PREFIX)
            ),
            "ScanIndexForward": False,
            "Limit": limit,
        }
        if start_key is not None:
            kwargs["ExclusiveStartKey"] = start_key
        response = self._table.query(**kwargs)
        items = [dict(i) for i in response.get("Items", [])]
        next_key = response.get("LastEvaluatedKey")
        return items, (dict(next_key) if next_key else None)


def build_diagnostic_item(
    *,
    device_id: str,
    event: dict[str, Any],
    received_at: str,
    expires_at: int,
    event_sha: str,
) -> dict[str, Any]:
    """Assemble the stored diagnostic-event item (B.10 item shape).

    ``checks``/``alerts``/``metrics`` are kept as a compact JSON string in
    ``payload`` (avoids float->Decimal and keeps items small); fields the API
    returns or filters on are native attributes.
    """
    payload = json.dumps(
        {
            "checks": event.get("checks", []),
            "alerts": event.get("alerts", []),
            "metrics": event.get("metrics", []),
        },
        separators=(",", ":"),
    )
    return {
        "PK": _device_pk(device_id),
        "SK": _diag_sk(event["event_id"]),
        "entity": "diagnostic",
        "device_id": device_id,
        "event_id": event["event_id"],
        "event_type": event["event_type"],
        "schema_version": event["schema_version"],
        "timestamp": event["timestamp"],
        "received_at": received_at,
        "source": event["source"],
        "status": event["status"],
        "network_status": event["network_status"],
        "alert_count": len(event.get("alerts", [])),
        "payload_sha256": event_sha,
        "payload": payload,
        "expires_at": expires_at,
    }


def diagnostic_to_public(item: dict[str, Any]) -> dict[str, Any]:
    """Map a stored diagnostic item to the public diagnostics list object."""
    payload_raw = item.get("payload")
    try:
        payload = json.loads(payload_raw) if isinstance(payload_raw, str) else {}
    except ValueError:
        payload = {}
    public = {
        "event_id": item.get("event_id"),
        "timestamp": item.get("timestamp"),
        "received_at": item.get("received_at"),
        "source": item.get("source"),
        "status": item.get("status"),
        "network_status": item.get("network_status"),
        "alert_count": item.get("alert_count"),
        "checks": payload.get("checks", []),
        "alerts": payload.get("alerts", []),
        "metrics": payload.get("metrics", []),
    }
    converted: dict[str, Any] = _decimals_to_int(public)
    return converted


def _stored_scalar(item: dict[str, Any], key: str) -> Any:
    """Read a scalar from an item that may use DynamoDB wire format.

    ``ReturnValuesOnConditionCheckFailure`` items come back from the low-level
    error payload in attribute-value form (``{"S": "..."}``); the resource layer
    returns plain values. Handle both so the hash compare is robust.
    """
    value = item.get(key)
    if isinstance(value, dict) and "S" in value:
        return value["S"]
    return value
