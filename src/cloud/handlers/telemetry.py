"""Telemetry handler: ingest 1-10 diagnostic events (design B.11).

``POST /v1/telemetry`` (ingest scope). Processing order (B.11): check body size,
parse JSON, validate the envelope, ``GetItem`` the device (missing -> 409), then
a conditional put per valid event, then AP6/AP6b for the latest status, then the
per-item response. A transient DynamoDB error mid-batch aborts with 503; a retry
sees the already-written items as duplicates and still advances the status.
"""

from __future__ import annotations

import logging
from typing import Any

from cloud.auth import ApiKeyProvider, Scope
from cloud.config import CloudSettings
from cloud.errors import DeviceNotRegistered, ValidationFailed
from cloud.handlers._support import build_auth_provider, configure_root_logging
from cloud.http import (
    Request,
    Response,
    RouteContext,
    api_handler,
    json_response,
    parse_json_body,
    to_proxy_response,
)
from cloud.metrics import (
    TELEMETRY_ACCEPTED,
    TELEMETRY_DUPLICATE,
    TELEMETRY_REJECTED,
    emit_metric,
)
from cloud.repository import (
    DeviceRepository,
    DiagnosticRepository,
    IngestOutcome,
    build_diagnostic_item,
    get_table,
    payload_sha256,
)
from shared.schemas.common import MAX_REQUEST_BYTES
from shared.schemas.telemetry import validate_event, validate_telemetry_envelope
from shared.utils.timeutil import parse_iso, to_iso, utc_now

__all__ = ["handler", "REQUIRED_ENV", "SERVICE"]

REQUIRED_ENV = frozenset(
    {
        "TABLE_NAME",
        "INGEST_KEY_PARAMETER",
        "READ_KEY_PARAMETER",
        "DIAGNOSTIC_RETENTION_DAYS",
    }
)
SERVICE = "diagnostic-gateway"
_FUNCTION = "telemetry"
_LOG = logging.getLogger("cloud.telemetry")

_SECONDS_PER_DAY = 86_400

_settings: CloudSettings | None = None
_auth: ApiKeyProvider | None = None


def _ensure_setup() -> CloudSettings:
    global _settings, _auth
    if _settings is None:
        _settings = CloudSettings.load(required=REQUIRED_ENV)
        configure_root_logging(_settings.log_level)
        _auth = build_auth_provider(
            _settings.ingest_key_parameter or "", _settings.read_key_parameter or ""
        )
    return _settings


@api_handler(scope=Scope.INGEST)
def _ingest(ctx: RouteContext) -> Response:
    settings = ctx.extra["settings"]
    body = parse_json_body(ctx.request, max_bytes=MAX_REQUEST_BYTES)

    envelope_issues = validate_telemetry_envelope(body)
    if envelope_issues:
        raise ValidationFailed(
            details=[{"field": i.field, "issue": i.message} for i in envelope_issues]
        )

    device_id = body["device_id"]
    events = body["events"]

    table = get_table(settings.table_name)
    device_repo = DeviceRepository(table)
    diag_repo = DiagnosticRepository(table)

    if device_repo.get(device_id) is None:
        raise DeviceNotRegistered()

    received_at = to_iso(utc_now())
    retention_days = settings.diagnostic_retention_days or 30

    results, newest = _process_events(
        events,
        device_id=device_id,
        diag_repo=diag_repo,
        received_at=received_at,
        retention_days=retention_days,
        ctx=ctx,
    )

    _update_profile(device_repo, device_id, newest, received_at)

    accepted = sum(1 for r in results if r["status"] == "accepted")
    duplicates = sum(1 for r in results if r["status"] == "duplicate")
    rejected = sum(1 for r in results if r["status"] == "rejected")
    return json_response(
        200,
        {
            "device_id": device_id,
            "accepted": accepted,
            "duplicates": duplicates,
            "rejected": rejected,
            "results": results,
        },
    )


def _process_events(
    events: list[dict[str, Any]],
    *,
    device_id: str,
    diag_repo: DiagnosticRepository,
    received_at: str,
    retention_days: int,
    ctx: RouteContext,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Validate and conditionally write each event; return (results, newest).

    ``newest`` is the accepted-or-duplicate event with the largest ``event_id``
    (UUIDv7 is time-ordered), used to drive AP6. A transient DynamoDB error
    propagates so the whole request aborts with 503.
    """
    results: list[dict[str, Any]] = []
    newest: dict[str, Any] | None = None
    expires_at = _expires_at(received_at, retention_days)

    for index, event in enumerate(events):
        code, issues = validate_event(event)
        if code is not None:
            results.append(_rejected_item(event, index, code, issues))
            emit_metric(TELEMETRY_REJECTED, service=ctx.service,
                        function=ctx.function)
            continue
        event_sha = payload_sha256(event)
        item = build_diagnostic_item(
            device_id=device_id,
            event=event,
            received_at=received_at,
            expires_at=expires_at,
            event_sha=event_sha,
        )
        outcome = diag_repo.put_event(item, event_sha=event_sha)
        if outcome is IngestOutcome.CONFLICT:
            results.append(
                {
                    "event_id": event["event_id"],
                    "status": "rejected",
                    "error": {
                        "code": "EVENT_ID_CONFLICT",
                        "message": "event_id already used with a different payload",
                    },
                }
            )
            emit_metric(TELEMETRY_REJECTED, service=ctx.service,
                        function=ctx.function)
            continue
        status = "accepted" if outcome is IngestOutcome.ACCEPTED else "duplicate"
        results.append({"event_id": event["event_id"], "status": status})
        emit_metric(
            TELEMETRY_ACCEPTED if status == "accepted" else TELEMETRY_DUPLICATE,
            service=ctx.service,
            function=ctx.function,
        )
        if newest is None or event["event_id"] > newest["event_id"]:
            newest = event
    return results, newest


def _update_profile(
    device_repo: DeviceRepository,
    device_id: str,
    newest: dict[str, Any] | None,
    received_at: str,
) -> None:
    """AP6 for the newest accepted/duplicate event, else AP6b alone."""
    if newest is None:
        device_repo.touch_last_seen(device_id, received_at=received_at)
        return
    device_repo.update_latest(
        device_id,
        event_id=newest["event_id"],
        status=newest["status"],
        network_status=newest["network_status"],
        event_at=newest["timestamp"],
        received_at=received_at,
    )


def _rejected_item(
    event: Any, index: int, code: str, issues: list[Any]
) -> dict[str, Any]:
    event_id = event.get("event_id") if isinstance(event, dict) else None
    error: dict[str, Any] = {
        "code": code,
        "message": "Event validation failed."
        if code == "VALIDATION_ERROR"
        else "Event timestamp is too far in the future.",
    }
    if code in {"VALIDATION_ERROR", "CLOCK_SKEW"} and issues:
        error["details"] = [
            {"field": i.field, "issue": i.message} for i in issues[:10]
        ]
    item: dict[str, Any] = {"status": "rejected", "error": error}
    if event_id is not None:
        item["event_id"] = event_id
    else:
        item["event_id"] = f"events[{index}]"
    return item


def _expires_at(received_at: str, retention_days: int) -> int:
    received = parse_iso(received_at)
    return int(received.timestamp()) + retention_days * _SECONDS_PER_DAY


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Lambda entry point for ``POST /v1/telemetry``."""
    settings = _ensure_setup()
    request = Request.from_event(event)
    ctx = RouteContext(
        request=request,
        service=SERVICE,
        function=_FUNCTION,
        auth=_auth,
        extra={"settings": settings},
    )
    return to_proxy_response(_ingest(ctx))
