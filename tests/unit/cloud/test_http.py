"""HTTP request parsing and the @api_handler exception-mapping table."""

from __future__ import annotations

import base64
import json

from botocore.exceptions import ClientError

from cloud.errors import (
    DependencyUnavailable,
    InvalidJsonError,
    NotFound,
    PayloadTooLarge,
    ValidationFailed,
)
from cloud.http import (
    Request,
    RouteContext,
    api_handler,
    json_response,
    parse_json_body,
    to_proxy_response,
)


def _event(**overrides) -> dict:
    event = {
        "routeKey": "GET /health",
        "rawPath": "/health",
        "headers": {"Authorization": "Bearer x", "X-Trace": "1"},
        "queryStringParameters": {"limit": "5"},
        "pathParameters": {"device_id": "abc"},
        "body": None,
        "isBase64Encoded": False,
        "requestContext": {"requestId": "req-1", "http": {"method": "GET"}},
    }
    event.update(overrides)
    return event


def _ctx(request: Request) -> RouteContext:
    return RouteContext(request=request, service="svc", function="fn", auth=None)


def test_request_parsing_lowercases_headers() -> None:
    request = Request.from_event(_event())
    assert request.headers["authorization"] == "Bearer x"
    assert request.method == "GET"
    assert request.path_parameters["device_id"] == "abc"
    assert request.query_parameters["limit"] == "5"
    assert request.request_id == "req-1"


def test_base64_body_is_decoded() -> None:
    encoded = base64.b64encode(b'{"a":1}').decode("ascii")
    request = Request.from_event(_event(body=encoded, isBase64Encoded=True))
    assert request.body == '{"a":1}'


def test_missing_headers_default_to_empty() -> None:
    request = Request.from_event({"requestContext": {}})
    assert request.headers == {}
    assert request.body == ""


def test_parse_json_body_rejects_oversized() -> None:
    request = Request.from_event(_event(body="x" * 20))
    try:
        parse_json_body(request, max_bytes=5)
    except PayloadTooLarge:
        return
    raise AssertionError("expected PayloadTooLarge")


def test_parse_json_body_rejects_non_object() -> None:
    request = Request.from_event(_event(body="[1,2,3]"))
    try:
        parse_json_body(request, max_bytes=1024)
    except InvalidJsonError:
        return
    raise AssertionError("expected InvalidJsonError")


def _run(func, event=None) -> dict:
    request = Request.from_event(event or _event())
    return to_proxy_response(func(_ctx(request)))


def test_validation_error_maps_to_400() -> None:
    @api_handler(scope=None)
    def route(ctx: RouteContext):
        raise ValidationFailed(details=[{"field": "x", "issue": "bad"}])

    result = _run(route)
    assert result["statusCode"] == 400
    body = json.loads(result["body"])
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["details"] == [{"field": "x", "issue": "bad"}]
    assert body["error"]["request_id"] == "req-1"


def test_not_found_maps_to_404() -> None:
    @api_handler(scope=None)
    def route(ctx: RouteContext):
        raise NotFound()

    assert _run(route)["statusCode"] == 404


def test_dependency_unavailable_sets_retry_after() -> None:
    @api_handler(scope=None)
    def route(ctx: RouteContext):
        raise DependencyUnavailable()

    result = _run(route)
    assert result["statusCode"] == 503
    assert result["headers"]["Retry-After"] == "5"


def test_transient_client_error_maps_to_503() -> None:
    @api_handler(scope=None)
    def route(ctx: RouteContext):
        raise ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "slow down"}},
            "PutItem",
        )

    result = _run(route)
    assert result["statusCode"] == 503


def test_other_client_error_maps_to_500() -> None:
    @api_handler(scope=None)
    def route(ctx: RouteContext):
        raise ClientError(
            {"Error": {"Code": "ValidationException", "Message": "bad"}}, "PutItem"
        )

    result = _run(route)
    assert result["statusCode"] == 500


def test_unexpected_exception_maps_to_generic_500() -> None:
    @api_handler(scope=None)
    def route(ctx: RouteContext):
        raise RuntimeError("boom with secret details")

    result = _run(route)
    assert result["statusCode"] == 500
    body = json.loads(result["body"])
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "boom" not in result["body"]  # no traceback or message leaked


def test_details_capped_at_20() -> None:
    @api_handler(scope=None)
    def route(ctx: RouteContext):
        raise ValidationFailed(
            details=[{"field": f"f{i}", "issue": "x"} for i in range(50)]
        )

    body = json.loads(_run(route)["body"])
    assert len(body["error"]["details"]) == 20


def test_success_response_is_json() -> None:
    @api_handler(scope=None)
    def route(ctx: RouteContext):
        return json_response(200, {"ok": True})

    result = _run(route)
    assert result["statusCode"] == 200
    assert result["headers"]["Content-Type"] == "application/json"
    assert json.loads(result["body"]) == {"ok": True}
