"""ApiClient ordered classification tests (design B.9, seven-row table).

The first matching row wins. A parametrized case covers status x body shape
(envelope / bare {message} / empty).
"""

from __future__ import annotations

import json

import pytest

from agent.config.settings import Secret
from agent.sync.client import (
    ApiClient,
    AuthError,
    ConfigurationError,
    ConnectivityError,
    DeliveryUncertainError,
    DeviceNotRegisteredError,
    HttpResponse,
    MalformedResponseError,
    OfflineError,
    PayloadTooLargeError,
    PermanentSyncError,
    TransientSyncError,
)
from shared.utils.ids import new_uuid7


class _CannedTransport:
    """Returns a prepared response or raises a prepared transport error."""

    def __init__(self, response: HttpResponse | None = None, error=None) -> None:  # type: ignore[no-untyped-def]
        self._response = response
        self._error = error
        self.calls: list[str] = []

    def request(self, method, url, headers, body, timeout):  # type: ignore[no-untyped-def]
        self.calls.append(url)
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


def _client(transport: _CannedTransport) -> ApiClient:
    return ApiClient("https://api.example", Secret("k" * 32), transport, 5.0)


def _envelope(code: str) -> bytes:
    return json.dumps({"error": {"code": code, "message": "x"}}).encode()


def _events(n: int = 1) -> list[dict]:
    return [{"event_id": new_uuid7()} for _ in range(n)]


# --- transport-level rows ----------------------------------------------------
def test_connectivity_is_offline() -> None:
    client = _client(_CannedTransport(error=ConnectivityError("dns")))
    with pytest.raises(OfflineError):
        client.send_telemetry("dev", _events())


def test_delivery_uncertain_is_transient() -> None:
    client = _client(_CannedTransport(error=DeliveryUncertainError("reset")))
    with pytest.raises(TransientSyncError):
        client.send_telemetry("dev", _events())


# --- status rows -------------------------------------------------------------
def test_redirect_is_configuration_and_target_not_requested() -> None:
    transport = _CannedTransport(
        HttpResponse(301, {"Location": "https://evil.example/"}, b"")
    )
    client = _client(transport)
    with pytest.raises(ConfigurationError):
        client.send_telemetry("dev", _events())
    # The client made exactly one request; the redirect target was never called.
    assert transport.calls == ["https://api.example/v1/telemetry"]


@pytest.mark.parametrize("status", [401, 403])
def test_auth_statuses(status: int) -> None:
    client = _client(_CannedTransport(HttpResponse(status, {}, b"")))
    with pytest.raises(AuthError):
        client.send_telemetry("dev", _events())


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_transient_statuses(status: int) -> None:
    body = b'{"message":"Too Many Requests"}'
    client = _client(_CannedTransport(HttpResponse(status, {}, body)))
    with pytest.raises(TransientSyncError):
        client.send_telemetry("dev", _events())


def test_409_device_not_registered() -> None:
    client = _client(
        _CannedTransport(HttpResponse(409, {}, _envelope("DEVICE_NOT_REGISTERED")))
    )
    with pytest.raises(DeviceNotRegisteredError):
        client.send_telemetry("dev", _events())


def test_413_multi_event_is_payload_too_large() -> None:
    client = _client(
        _CannedTransport(HttpResponse(413, {}, _envelope("PAYLOAD_TOO_LARGE")))
    )
    with pytest.raises(PayloadTooLargeError):
        client.send_telemetry("dev", _events(2))


def test_413_single_event_is_permanent() -> None:
    client = _client(
        _CannedTransport(HttpResponse(413, {}, _envelope("PAYLOAD_TOO_LARGE")))
    )
    with pytest.raises(PermanentSyncError):
        client.send_telemetry("dev", _events(1))


def test_enveloped_400_is_permanent() -> None:
    client = _client(
        _CannedTransport(HttpResponse(400, {}, _envelope("VALIDATION_ERROR")))
    )
    with pytest.raises(PermanentSyncError):
        client.send_telemetry("dev", _events())


def test_non_envelope_404_is_configuration() -> None:
    body = b'{"message":"Not Found"}'
    client = _client(_CannedTransport(HttpResponse(404, {}, body)))
    with pytest.raises(ConfigurationError):
        client.send_telemetry("dev", _events())


def test_unlisted_5xx_is_configuration() -> None:
    client = _client(_CannedTransport(HttpResponse(501, {}, b"")))
    with pytest.raises(ConfigurationError):
        client.send_telemetry("dev", _events())


# --- 2xx body shapes ---------------------------------------------------------
def test_malformed_2xx_is_transient() -> None:
    client = _client(_CannedTransport(HttpResponse(200, {}, b"not json")))
    with pytest.raises(MalformedResponseError):
        client.send_telemetry("dev", _events())


def test_2xx_results_not_matching_sent_ids_is_malformed() -> None:
    body = json.dumps(
        {"results": [{"event_id": new_uuid7(), "status": "accepted"}]}
    ).encode()
    client = _client(_CannedTransport(HttpResponse(200, {}, body)))
    with pytest.raises(MalformedResponseError):
        client.send_telemetry("dev", _events())


def test_2xx_wellformed_returns_items() -> None:
    events = _events()
    body = json.dumps(
        {"results": [{"event_id": events[0]["event_id"], "status": "accepted"}]}
    ).encode()
    client = _client(_CannedTransport(HttpResponse(200, {}, body)))
    result = client.send_telemetry("dev", events)
    assert result.results[0].status == "accepted"


# --- status x body-shape matrix ---------------------------------------------
@pytest.mark.parametrize("status", [400, 404, 409, 413, 429, 500, 501])
@pytest.mark.parametrize("shape", ["envelope", "message", "empty"])
def test_status_body_matrix_classifies_without_crashing(
    status: int, shape: str
) -> None:
    if shape == "envelope":
        body = _envelope("SOME_CODE" if status != 409 else "DEVICE_NOT_REGISTERED")
    elif shape == "message":
        body = b'{"message":"info"}'
    else:
        body = b""
    client = _client(_CannedTransport(HttpResponse(status, {}, body)))
    # Every combination must map to exactly one of the client exceptions.
    with pytest.raises(
        (
            AuthError,
            TransientSyncError,
            ConfigurationError,
            PermanentSyncError,
            PayloadTooLargeError,
            DeviceNotRegisteredError,
        )
    ):
        client.send_telemetry("dev", _events(2))


def test_registration_2xx_returns_result() -> None:
    body = json.dumps({"device_id": "dev", "created": True}).encode()
    client = _client(_CannedTransport(HttpResponse(201, {}, body)))
    result = client.register_device({"device_id": "dev"})
    assert result.created is True
