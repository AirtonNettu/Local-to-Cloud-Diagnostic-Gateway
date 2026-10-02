"""Device handler: register/update and read device profiles (design B.11).

Routes on ``routeKey``: ``POST /v1/devices`` (ingest scope, idempotent upsert),
``GET /v1/devices`` (read scope, paginated list) and
``GET /v1/devices/{device_id}`` (read scope, one profile). Dependencies are
built once per warm container and cached in module globals.
"""

from __future__ import annotations

from typing import Any

from cloud.auth import ApiKeyProvider, Scope
from cloud.config import CloudSettings
from cloud.cursor import decode_device_cursor, encode_cursor
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
    parse_json_body,
    to_proxy_response,
)
from cloud.metrics import DEVICE_REGISTERED, emit_metric
from cloud.repository import DeviceRepository, get_table, to_public
from shared.schemas.common import DEVICE_ID_PATTERN, MAX_REGISTRATION_BYTES
from shared.schemas.device import validate_device_registration
from shared.utils.timeutil import to_iso, utc_now

__all__ = ["handler", "REQUIRED_ENV", "SERVICE"]

REQUIRED_ENV = frozenset({"TABLE_NAME", "INGEST_KEY_PARAMETER", "READ_KEY_PARAMETER"})
SERVICE = "diagnostic-gateway"
_FUNCTION = "device"

_DEFAULT_LIMIT = 25
_MAX_LIMIT = 100

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


def _repo() -> DeviceRepository:
    assert _settings is not None  # noqa: S101 - set by _ensure_setup
    return DeviceRepository(get_table(_settings.table_name or ""))


@api_handler(scope=Scope.INGEST)
def _register(ctx: RouteContext) -> Response:
    body = parse_json_body(ctx.request, max_bytes=MAX_REGISTRATION_BYTES)
    issues = validate_device_registration(body)
    if issues:
        raise ValidationFailed(
            details=[{"field": i.field, "issue": i.message} for i in issues]
        )
    now = to_iso(utc_now())
    created = _repo().upsert(body, now_iso=now)
    emit_metric(DEVICE_REGISTERED, service=ctx.service, function=ctx.function)
    return json_response(
        201 if created else 200,
        {
            "device_id": body["device_id"],
            "created": created,
            "registered_at": now,
            "updated_at": now,
        },
    )


@api_handler(scope=Scope.READ)
def _list(ctx: RouteContext) -> Response:
    limit = parse_limit(
        ctx.request.query_parameters.get("limit"),
        default=_DEFAULT_LIMIT,
        minimum=1,
        maximum=_MAX_LIMIT,
    )
    raw_cursor = ctx.request.query_parameters.get("cursor")
    start_key = decode_device_cursor(raw_cursor) if raw_cursor else None
    items, next_key = _repo().list_devices(limit=limit, start_key=start_key)
    return json_response(
        200,
        {
            "items": [to_public(item) for item in items],
            "next_cursor": encode_cursor(next_key) if next_key else None,
        },
    )


@api_handler(scope=Scope.READ)
def _get(ctx: RouteContext) -> Response:
    device_id = ctx.request.path_parameters.get("device_id", "")
    if not DEVICE_ID_PATTERN.match(device_id):
        raise ValidationFailed(
            details=[{"field": "device_id", "issue": "has an invalid format"}]
        )
    item = _repo().get(device_id)
    if item is None:
        raise NotFound("Device not found.")
    return json_response(200, to_public(item))


def _route(ctx: RouteContext) -> Response:
    route_key = ctx.request.route_key
    if route_key == "POST /v1/devices":
        return _register(ctx)
    if route_key == "GET /v1/devices":
        return _list(ctx)
    if route_key == "GET /v1/devices/{device_id}":
        return _get(ctx)
    # Unknown routes are handled by API Gateway, but guard defensively.
    return json_response(
        404,
        {
            "error": {
                "code": "NOT_FOUND",
                "message": "Resource not found.",
                "request_id": ctx.request.request_id,
            }
        },
    )


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Lambda entry point for the device routes."""
    _ensure_setup()
    request = Request.from_event(event)
    ctx = RouteContext(
        request=request, service=SERVICE, function=_FUNCTION, auth=_auth
    )
    return to_proxy_response(_route(ctx))
