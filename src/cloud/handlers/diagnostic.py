"""Diagnostic handler: recent diagnostics for a device (design B.11).

``GET /v1/devices/{device_id}/diagnostics`` (read scope). Returns events newest
first with cursor pagination; an unknown device is a 404 and a tampered cursor
is a 400 ``INVALID_CURSOR``.
"""

from __future__ import annotations

from typing import Any

from cloud.auth import ApiKeyProvider, Scope
from cloud.config import CloudSettings
from cloud.cursor import decode_diagnostic_cursor, encode_cursor
from cloud.errors import NotFound, ValidationFailed
from cloud.handlers._support import (
    build_auth_provider,
    configure_root_logging,
    parse_limit,
)
from cloud.http import (
    Request,
    Response,
    RouteContext,
    api_handler,
    json_response,
    to_proxy_response,
)
from cloud.repository import (
    DeviceRepository,
    DiagnosticRepository,
    diagnostic_to_public,
    get_table,
)
from shared.schemas.common import DEVICE_ID_PATTERN

__all__ = ["handler", "REQUIRED_ENV", "SERVICE"]

REQUIRED_ENV = frozenset({"TABLE_NAME", "INGEST_KEY_PARAMETER", "READ_KEY_PARAMETER"})
SERVICE = "diagnostic-gateway"
_FUNCTION = "diagnostic"

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 50

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


@api_handler(scope=Scope.READ)
def _list_diagnostics(ctx: RouteContext) -> Response:
    assert _settings is not None  # noqa: S101 - set by _ensure_setup
    device_id = ctx.request.path_parameters.get("device_id", "")
    if not DEVICE_ID_PATTERN.match(device_id):
        raise ValidationFailed(
            details=[{"field": "device_id", "issue": "has an invalid format"}]
        )

    limit = parse_limit(
        ctx.request.query_parameters.get("limit"),
        default=_DEFAULT_LIMIT,
        minimum=1,
        maximum=_MAX_LIMIT,
    )
    raw_cursor = ctx.request.query_parameters.get("cursor")
    start_key = (
        decode_diagnostic_cursor(raw_cursor, device_id=device_id)
        if raw_cursor
        else None
    )

    table = get_table(_settings.table_name or "")
    if DeviceRepository(table).get(device_id) is None:
        raise NotFound("Device not found.")

    items, next_key = DiagnosticRepository(table).query_recent(
        device_id, limit=limit, start_key=start_key
    )
    return json_response(
        200,
        {
            "device_id": device_id,
            "items": [diagnostic_to_public(item) for item in items],
            "next_cursor": encode_cursor(next_key) if next_key else None,
        },
    )


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Lambda entry point for the diagnostics route."""
    _ensure_setup()
    request = Request.from_event(event)
    ctx = RouteContext(
        request=request, service=SERVICE, function=_FUNCTION, auth=_auth
    )
    return to_proxy_response(_list_diagnostics(ctx))
