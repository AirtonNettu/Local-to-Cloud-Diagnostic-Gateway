"""HTTP transport and the sync ApiClient (design B.9).

``HttpTransport`` is a Protocol: it returns an ``HttpResponse`` for any status
(2xx/3xx/4xx/5xx are data, never exceptions) and raises a ``TransportError``
subclass only for network-level failures. ``UrllibTransport`` refuses redirects
(so the ingest key is never copied to another host) and maps CPython exceptions
by *where they are raised*: an ``OSError`` wrapped in ``URLError`` from
``do_open`` means the request was provably not delivered (``ConnectivityError``);
anything after the request was sent is ``DeliveryUncertainError``.

``ApiClient`` turns a response into a typed result or raises per the ordered
seven-row classification table. The first matching row wins.
"""

from __future__ import annotations

import http.client
import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

from agent import __version__
from agent.config.settings import Secret

__all__ = [
    "HttpResponse",
    "HttpTransport",
    "UrllibTransport",
    "TransportError",
    "ConnectivityError",
    "DeliveryUncertainError",
    "SyncClientError",
    "OfflineError",
    "TransientSyncError",
    "MalformedResponseError",
    "AuthError",
    "ConfigurationError",
    "PermanentSyncError",
    "PayloadTooLargeError",
    "DeviceNotRegisteredError",
    "ItemResult",
    "TelemetryResult",
    "RegistrationResult",
    "ApiClient",
]

MAX_RESPONSE_BYTES = 1024 * 1024  # 1 MiB

_TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})


# --- transport ---------------------------------------------------------------
@dataclass(frozen=True)
class HttpResponse:
    """A completed HTTP response: status and body are data, never exceptions."""

    status: int
    headers: dict[str, str]
    body: bytes


class TransportError(Exception):
    """Base for network-level failures. Never raised directly."""


class ConnectivityError(TransportError):
    """The request was provably not delivered to the server."""


class DeliveryUncertainError(TransportError):
    """The request was (or may have been) fully sent; outcome unknown."""


class HttpTransport(Protocol):
    """Pluggable HTTP transport (injected so the client is unit-testable)."""

    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect; urllib then raises ``HTTPError(3xx)``.

    Following a redirect would re-issue the POST as GET and copy the
    Authorization header to another host, leaking the ingest key.
    """

    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


class UrllibTransport:
    """A urllib-based transport with no redirects and precise error mapping."""

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
            _NoRedirect(),
        )

    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        request = urllib.request.Request(url, data=body, method=method)  # noqa: S310
        for key, value in headers.items():
            request.add_header(key, value)
        try:
            with self._opener.open(request, timeout=timeout) as resp:  # noqa: S310
                return self._read(resp.status, dict(resp.headers), resp)
        except urllib.error.HTTPError as exc:
            raw = exc.read(MAX_RESPONSE_BYTES + 1)
            return HttpResponse(
                exc.code, dict(exc.headers or {}), raw[:MAX_RESPONSE_BYTES]
            )
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, OSError):
                raise ConnectivityError(str(exc.reason)) from exc
            raise ConfigurationError(f"invalid URL: {exc.reason}") from exc
        except (
            TimeoutError,
            ConnectionResetError,
            ConnectionAbortedError,
            http.client.HTTPException,
            ssl.SSLError,
            OSError,
        ) as exc:
            raise DeliveryUncertainError(str(exc)) from exc

    @staticmethod
    def _read(status: int, headers: dict[str, str], resp: Any) -> HttpResponse:
        raw = resp.read(MAX_RESPONSE_BYTES + 1)
        return HttpResponse(status, headers, raw[:MAX_RESPONSE_BYTES])


# --- client errors -----------------------------------------------------------
class SyncClientError(Exception):
    """Base for every error the ApiClient raises."""


class OfflineError(SyncClientError):
    """Row 1: not delivered; the cycle is aborted and events stay pending."""


class TransientSyncError(SyncClientError):
    """Rows 1/4/5/6: retry with backoff, DEAD_LETTER at the retry limit."""

    def __init__(self, message: str, *, http_status: int | None = None) -> None:
        super().__init__(message)
        self.http_status = http_status


class MalformedResponseError(TransientSyncError):
    """Row 5: a 2xx body that is not the documented shape (retry is safe)."""


class AuthError(SyncClientError):
    """Row 3: 401/403; the cycle is aborted and events are released."""


class ConfigurationError(SyncClientError):
    """Rows 2/7: redirect or an unexpected status; cycle aborted, released."""

    def __init__(self, message: str, *, http_status: int | None = None) -> None:
        super().__init__(message)
        self.http_status = http_status


class PermanentSyncError(SyncClientError):
    """Row 6: enveloped 4xx or single-event 413; DEAD_LETTER."""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class PayloadTooLargeError(SyncClientError):
    """Row 6: 413 on a multi-event request; resend one event per request."""


class DeviceNotRegisteredError(SyncClientError):
    """Row 6: 409 DEVICE_NOT_REGISTERED; re-register once then resend."""


# --- client results ----------------------------------------------------------
@dataclass(frozen=True)
class ItemResult:
    """Per-event outcome parsed from a well-formed 200 telemetry response."""

    event_id: str
    status: str  # accepted | duplicate | rejected
    code: str | None = None  # error code when rejected (e.g. CLOCK_SKEW)
    message: str | None = None


@dataclass(frozen=True)
class TelemetryResult:
    """A well-formed telemetry response: the per-item results."""

    results: list[ItemResult] = field(default_factory=list)
    request_id: str | None = None


@dataclass(frozen=True)
class RegistrationResult:
    """A successful device registration."""

    device_id: str
    created: bool
    request_id: str | None = None


# --- the client --------------------------------------------------------------
class ApiClient:
    """Sends registration and telemetry, classifying every outcome (B.9)."""

    def __init__(
        self,
        base_url: str,
        api_key: Secret,
        transport: HttpTransport,
        timeout: float,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._key = api_key
        self._transport = transport
        self._timeout = timeout

    def register_device(self, payload: dict[str, Any]) -> RegistrationResult:
        """POST /v1/devices. Returns the result or raises per the table."""
        response = self._send("POST", "/v1/devices", payload)
        self._classify_transport(response)
        request_id = self._request_id(response)
        if 200 <= response.status < 300:
            body = self._json(response)
            if not isinstance(body, dict) or "device_id" not in body:
                raise MalformedResponseError("registration response has no device_id")
            return RegistrationResult(
                device_id=str(body["device_id"]),
                created=bool(body.get("created", False)),
                request_id=request_id,
            )
        self._raise_for_error_status(response)
        raise ConfigurationError(
            f"unexpected {response.status} from API; check API_BASE_URL",
            http_status=response.status,
        )

    def send_telemetry(
        self, device_id: str, events: list[dict[str, Any]]
    ) -> TelemetryResult:
        """POST /v1/telemetry. Returns per-item results or raises per the table."""
        payload = {"schema_version": 1, "device_id": device_id, "events": events}
        response = self._send("POST", "/v1/telemetry", payload)
        self._classify_transport(response)
        request_id = self._request_id(response)
        if 200 <= response.status < 300:
            return self._parse_telemetry(response, events, request_id)
        self._raise_for_error_status(response, event_count=len(events))
        raise ConfigurationError(
            f"unexpected {response.status} from API; check API_BASE_URL",
            http_status=response.status,
        )

    # -- transport + ordered classification ------------------------------
    def _send(
        self, method: str, path: str, payload: dict[str, Any]
    ) -> HttpResponse:
        url = self._base + path
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._key.reveal()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"diagnostic-agent/{__version__}",
        }
        try:
            return self._transport.request(method, url, headers, body, self._timeout)
        except ConnectivityError as exc:  # row 1: not delivered
            raise OfflineError(str(exc)) from exc
        except DeliveryUncertainError as exc:  # row 1: delivery uncertain
            raise TransientSyncError(str(exc)) from exc

    @staticmethod
    def _classify_transport(response: HttpResponse) -> None:
        # Rows 2 and 3xx handling: a 3xx reached here only via _NoRedirect.
        if 300 <= response.status < 400:
            location = response.headers.get("Location", "")
            raise ConfigurationError(
                "API_BASE_URL redirects "
                f"({response.status} to {location}); configure the final https URL",
                http_status=response.status,
            )

    def _raise_for_error_status(
        self, response: HttpResponse, *, event_count: int = 1
    ) -> None:
        status = response.status
        if status in (401, 403):  # row 3
            raise AuthError(f"authentication failed ({status})")
        if status in _TRANSIENT_STATUSES:  # row 4
            raise TransientSyncError(
                f"transient server status {status}", http_status=status
            )
        envelope_code = self._envelope_code(response)
        if envelope_code is not None:  # rows 6
            if status == 409 and envelope_code == "DEVICE_NOT_REGISTERED":
                raise DeviceNotRegisteredError("device not registered")
            if status == 413:
                if event_count > 1:
                    raise PayloadTooLargeError("payload too large; split the batch")
                raise PermanentSyncError(
                    "single event exceeds the request limit", code=envelope_code
                )
            if 400 <= status < 500:
                raise PermanentSyncError(
                    f"request rejected ({envelope_code})", code=envelope_code
                )
        # row 7: everything else (non-envelope 4xx, unlisted 5xx, other status)

    # -- helpers ----------------------------------------------------------
    def _parse_telemetry(
        self,
        response: HttpResponse,
        events: list[dict[str, Any]],
        request_id: str | None,
    ) -> TelemetryResult:
        body = self._json(response)
        if not isinstance(body, dict):
            raise MalformedResponseError("telemetry response is not a JSON object")
        results = body.get("results")
        if not isinstance(results, list):
            raise MalformedResponseError("telemetry response has no results list")
        parsed: list[ItemResult] = []
        for item in results:
            if not isinstance(item, dict) or "event_id" not in item:
                raise MalformedResponseError("telemetry result item is malformed")
            error = item.get("error")
            code = (
                str(error.get("code"))
                if isinstance(error, dict) and error.get("code") is not None
                else None
            )
            message = (
                str(error.get("message"))
                if isinstance(error, dict) and error.get("message") is not None
                else None
            )
            parsed.append(
                ItemResult(
                    event_id=str(item["event_id"]),
                    status=str(item.get("status", "")),
                    code=code,
                    message=message,
                )
            )
        sent_ids = {event["event_id"] for event in events}
        got_ids = {item.event_id for item in parsed}
        if got_ids != sent_ids:
            raise MalformedResponseError("telemetry results do not match sent events")
        return TelemetryResult(results=parsed, request_id=request_id)

    @staticmethod
    def _json(response: HttpResponse) -> Any:
        try:
            return json.loads(response.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None

    def _envelope_code(self, response: HttpResponse) -> str | None:
        body = self._json(response)
        if not isinstance(body, dict):
            return None
        error = body.get("error")
        if not isinstance(error, dict):
            return None
        code = error.get("code")
        return str(code) if isinstance(code, str) else None

    @staticmethod
    def _request_id(response: HttpResponse) -> str | None:
        for key in ("x-request-id", "X-Request-Id", "x-amzn-RequestId"):
            if key in response.headers:
                return response.headers[key]
        return None
