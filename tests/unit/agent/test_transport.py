"""UrllibTransport exception-mapping tests (design B.9).

The mapping is by *where CPython raises*, not errno lists: an ``OSError`` wrapped
in ``URLError`` (the ``do_open`` boundary) means the request was provably not
delivered (``ConnectivityError``); anything after the send is
``DeliveryUncertainError``; an ``HTTPError`` of any status becomes an
``HttpResponse``.
"""

from __future__ import annotations

import http.client
import io
import socket
import ssl
import urllib.error

import pytest

from agent.sync.client import (
    ConnectivityError,
    DeliveryUncertainError,
    UrllibTransport,
)


class _FakeOpener:
    def __init__(self, raiser) -> None:  # type: ignore[no-untyped-def]
        self._raiser = raiser

    def open(self, request, timeout):  # type: ignore[no-untyped-def]
        return self._raiser()


def _transport(raiser) -> UrllibTransport:  # type: ignore[no-untyped-def]
    transport = UrllibTransport()
    transport._opener = _FakeOpener(raiser)  # type: ignore[attr-defined]
    return transport


def _request(transport: UrllibTransport) -> object:
    return transport.request("POST", "https://api.example/v1/telemetry", {}, b"{}", 5.0)


def test_httperror_becomes_response() -> None:
    def raiser() -> None:
        raise urllib.error.HTTPError(
            "https://api.example/v1/telemetry",
            503,
            "Service Unavailable",
            {"Retry-After": "5"},
            io.BytesIO(b'{"error":{"code":"SERVICE_UNAVAILABLE"}}'),
        )

    response = _request(_transport(raiser))
    assert response.status == 503
    assert b"SERVICE_UNAVAILABLE" in response.body


def test_redirect_httperror_becomes_response() -> None:
    def raiser() -> None:
        raise urllib.error.HTTPError(
            "https://api.example/v1/telemetry",
            301,
            "Moved",
            {"Location": "https://evil.example/"},
            io.BytesIO(b""),
        )

    response = _request(_transport(raiser))
    assert response.status == 301
    assert response.headers.get("Location") == "https://evil.example/"


def test_oserror_in_urlerror_is_connectivity() -> None:
    def raiser() -> None:
        raise urllib.error.URLError(socket.gaierror("Name resolution failed"))

    with pytest.raises(ConnectivityError):
        _request(_transport(raiser))


def test_tls_verification_failure_is_connectivity() -> None:
    def raiser() -> None:
        raise urllib.error.URLError(ssl.SSLCertVerificationError("bad cert"))

    with pytest.raises(ConnectivityError):
        _request(_transport(raiser))


def test_error_after_send_is_delivery_uncertain() -> None:
    def raiser() -> None:
        raise http.client.RemoteDisconnected("peer closed")

    with pytest.raises(DeliveryUncertainError):
        _request(_transport(raiser))


def test_timeout_after_send_is_delivery_uncertain() -> None:
    def raiser() -> None:
        raise TimeoutError("read timed out")

    with pytest.raises(DeliveryUncertainError):
        _request(_transport(raiser))
