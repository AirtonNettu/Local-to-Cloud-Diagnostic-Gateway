"""HTTP API v2 request parsing and the ``@api_handler`` decorator (design B.14).

``Request`` is parsed from an API Gateway HTTP API (payload format 2.0) event:
method, raw path, path/query parameters, lowercased headers, decoded body and
the request id. ``@api_handler(scope)`` wraps each route function: it binds the
request id into the logging context, enforces the auth scope (when a scope is
given), runs the route and converts its result to the Lambda proxy response
shape. It maps every exception to the B.14 status/code/log-level/metric table so
a route never leaks a traceback to the client.
"""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from botocore.exceptions import ClientError

from cloud import metrics
from cloud.auth import ApiKeyProvider, Scope
from cloud.errors import (
    ApiError,
    DependencyUnavailable,
    InvalidJsonError,
    PayloadTooLarge,
    ValidationFailed,
)
from shared.utils.json_logging import log_context

__all__ = [
    "Request",
    "Response",
    "RouteContext",
    "api_handler",
    "json_response",
    "to_proxy_response",
    "parse_json_body",
]

_LOG = logging.getLogger("cloud.http")

_MAX_DETAILS = 20
_JSON_HEADERS = {"Content-Type": "application/json"}


@dataclass(frozen=True)
class Request:
    """A parsed HTTP API v2 request. Headers are lowercased by API Gateway."""

    method: str
    raw_path: str
    route_key: str
    path_parameters: dict[str, str]
    query_parameters: dict[str, str]
    headers: dict[str, str]
    body: str
    request_id: str

    @classmethod
    def from_event(cls, event: Mapping[str, Any]) -> Request:
        """Parse an HTTP API v2 event into a ``Request`` (body base64-decoded)."""
        request_context = event.get("requestContext", {}) or {}
        http = request_context.get("http", {}) or {}
        raw_headers = event.get("headers") or {}
        headers = {str(k).lower(): str(v) for k, v in raw_headers.items()}

        body = event.get("body")
        if body is not None and event.get("isBase64Encoded"):
            try:
                body = base64.b64decode(body).decode("utf-8", "replace")
            except (ValueError, TypeError):
                body = ""
        return cls(
            method=str(http.get("method", "")),
            raw_path=str(event.get("rawPath", "")),
            route_key=str(event.get("routeKey", "")),
            path_parameters={
                str(k): str(v)
                for k, v in (event.get("pathParameters") or {}).items()
            },
            query_parameters={
                str(k): str(v)
                for k, v in (event.get("queryStringParameters") or {}).items()
            },
            headers=headers,
            body=body if isinstance(body, str) else "",
            request_id=str(request_context.get("requestId", "")),
        )


@dataclass
class RouteContext:
    """What a route function receives: the parsed request and dependencies.

    ``service`` and ``function`` name the EMF dimensions. ``auth`` is the shared
    key provider (``None`` for public routes such as health).
    """

    request: Request
    service: str
    function: str
    auth: ApiKeyProvider | None = None
    extra: dict[str, Any] = field(default_factory=dict)


RouteFn = Callable[[RouteContext], "Response"]


@dataclass(frozen=True)
class Response:
    """A route's structured result before conversion to the proxy shape."""

    status: int
    body: Any
    headers: dict[str, str] = field(default_factory=dict)


def json_response(
    status: int, body: Any, *, headers: Mapping[str, str] | None = None
) -> Response:
    """Build a JSON ``Response`` with the ``application/json`` content type."""
    merged = dict(_JSON_HEADERS)
    if headers:
        merged.update(headers)
    return Response(status=status, body=body, headers=merged)


def api_handler(scope: Scope | None) -> Callable[[RouteFn], RouteFn]:
    """Decorate a route function with logging, auth and exception mapping.

    ``scope`` is the required auth scope, or ``None`` for a public route. The
    wrapped function still receives a ``RouteContext`` and returns a ``Response``;
    the decorator converts it to ``{"statusCode", "headers", "body"}`` and turns
    any raised ``ApiError``/AWS/other exception into the mapped envelope.
    """

    def decorator(func: RouteFn) -> RouteFn:
        def wrapper(ctx: RouteContext) -> Response:
            with log_context(request_id=ctx.request.request_id):
                try:
                    if scope is not None:
                        _enforce_scope(ctx, scope)
                    return func(ctx)
                except ApiError as exc:
                    return _render_api_error(exc, ctx)
                except Exception as exc:  # noqa: BLE001 - mapped to a 500 envelope.
                    return _render_unexpected(exc, ctx)

        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper

    return decorator


def _enforce_scope(ctx: RouteContext, scope: Scope) -> None:
    if ctx.auth is None:  # pragma: no cover - wiring guard.
        raise RuntimeError("a scoped route requires an auth provider")
    ctx.auth.authorize(ctx.request.headers, scope)


def _render_api_error(exc: ApiError, ctx: RouteContext) -> Response:
    """Map an ``ApiError`` to a response per the B.14 table (log + metric)."""
    exc.details = exc.details[:_MAX_DETAILS]
    _log_and_meter(exc, ctx)
    headers = dict(_JSON_HEADERS)
    headers.update(exc.extra_headers())
    return Response(
        status=exc.status,
        body=exc.to_envelope(ctx.request.request_id),
        headers=headers,
    )


def _log_and_meter(exc: ApiError, ctx: RouteContext) -> None:
    event = {
        InvalidJsonError: "invalid_json",
        ValidationFailed: "validation_error",
        PayloadTooLarge: "payload_too_large",
    }.get(type(exc), exc.code.lower())
    if isinstance(exc, DependencyUnavailable):
        _LOG.error(
            "dependency unavailable",
            extra={"event": "dependency_unavailable", "http_status": exc.status},
        )
        metrics.emit_metric(
            metrics.DYNAMODB_ERROR, service=ctx.service, function=ctx.function
        )
        return
    if exc.code in {"UNAUTHORIZED", "FORBIDDEN"}:
        # auth.py already logged a warning (without header contents).
        metrics.emit_metric(
            metrics.AUTH_FAILURE, service=ctx.service, function=ctx.function
        )
        return
    if exc.code in {"NOT_FOUND", "DEVICE_NOT_REGISTERED"}:
        _LOG.info(event, extra={"event": event, "http_status": exc.status})
        return
    # INVALID_JSON / VALIDATION_ERROR / PAYLOAD_TOO_LARGE: WARNING + metric.
    _LOG.warning(event, extra={"event": event, "http_status": exc.status})
    metrics.emit_metric(
        metrics.VALIDATION_ERROR, service=ctx.service, function=ctx.function
    )


def _render_unexpected(exc: Exception, ctx: RouteContext) -> Response:
    """Map an AWS or unknown exception to a 503 or a generic 500."""
    if isinstance(exc, ClientError):
        from cloud.repository import is_transient_client_error

        code = exc.response.get("Error", {}).get("Code", "")
        if is_transient_client_error(exc):
            _LOG.error(
                "dynamodb transient error",
                extra={"event": "dynamodb_error", "error": code},
            )
            metrics.emit_metric(
                metrics.DYNAMODB_ERROR, service=ctx.service, function=ctx.function
            )
            return _error_response(
                DependencyUnavailable(), ctx.request.request_id
            )
        _LOG.error(
            "dynamodb client error",
            extra={"event": "dynamodb_error", "error": code},
        )
        metrics.emit_metric(
            metrics.DYNAMODB_ERROR, service=ctx.service, function=ctx.function
        )
        return _generic_500(ctx)

    _LOG.error(
        "unhandled exception", exc_info=exc, extra={"event": "lambda_error"}
    )
    metrics.emit_metric(
        metrics.LAMBDA_ERROR, service=ctx.service, function=ctx.function
    )
    return _generic_500(ctx)


def _error_response(exc: ApiError, request_id: str) -> Response:
    headers = dict(_JSON_HEADERS)
    headers.update(exc.extra_headers())
    return Response(status=exc.status, body=exc.to_envelope(request_id),
                    headers=headers)


def _generic_500(ctx: RouteContext) -> Response:
    body = {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "An internal error occurred.",
            "request_id": ctx.request.request_id,
        }
    }
    return Response(status=500, body=body, headers=dict(_JSON_HEADERS))


def to_proxy_response(response: Response) -> dict[str, Any]:
    """Convert a ``Response`` to the Lambda HTTP API proxy result shape."""
    return {
        "statusCode": response.status,
        "headers": response.headers,
        "body": json.dumps(response.body, separators=(",", ":")),
    }


def parse_json_body(request: Request, *, max_bytes: int) -> dict[str, Any]:
    """Decode the request body as a JSON object, enforcing the size limit.

    Raises ``PayloadTooLarge`` when the UTF-8 body exceeds ``max_bytes`` and
    ``InvalidJsonError`` when it is not a JSON object.
    """
    encoded = request.body.encode("utf-8")
    if len(encoded) > max_bytes:
        raise PayloadTooLarge()
    try:
        parsed = json.loads(request.body) if request.body else None
    except ValueError as exc:
        raise InvalidJsonError() from exc
    if not isinstance(parsed, dict):
        raise InvalidJsonError("Request body must be a JSON object.")
    return parsed
