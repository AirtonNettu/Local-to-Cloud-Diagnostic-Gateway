"""Local HTTP server that dispatches to the real Lambda handlers (design B.20).

The ``ROUTES`` table is the single source of truth for (method, path, handler):
the template test asserts the SAM template's ``HttpApi`` events match it exactly,
so the local test server can never drift from the deployed API. ``LocalApiServer``
starts a ``ThreadingHTTPServer`` on ``127.0.0.1:0`` whose handler converts each
request into an HTTP API v2 event, routes it by this table and writes the
handler's response back. It is used by the agent sync end-to-end tests and the
``local_cloud`` dev tool, so no AWS is ever involved.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from cloud.handlers import device, diagnostic, health, telemetry

Handler = Callable[[dict[str, Any], Any], dict[str, Any]]


@dataclass(frozen=True)
class Route:
    """One API route: HTTP method, path template and the Lambda handler."""

    method: str
    path: str
    handler: Handler

    @property
    def route_key(self) -> str:
        return f"{self.method} {self.path}"


# The authoritative route table (compared with the template by the infra test).
ROUTES: tuple[Route, ...] = (
    Route("GET", "/health", health.handler),
    Route("POST", "/v1/devices", device.handler),
    Route("GET", "/v1/devices", device.handler),
    Route("GET", "/v1/devices/{device_id}", device.handler),
    Route("POST", "/v1/telemetry", telemetry.handler),
    Route("GET", "/v1/devices/{device_id}/diagnostics", diagnostic.handler),
)


def _compile(path: str) -> re.Pattern[str]:
    """Turn ``/v1/devices/{device_id}`` into an anchored regex with a group."""
    parts = []
    for segment in path.split("/"):
        if segment.startswith("{") and segment.endswith("}"):
            name = segment[1:-1]
            parts.append(f"(?P<{name}>[^/]+)")
        else:
            parts.append(re.escape(segment))
    return re.compile("^" + "/".join(parts) + "$")


_COMPILED = tuple((route, _compile(route.path)) for route in ROUTES)


def match_route(method: str, path: str) -> tuple[Route, dict[str, str]] | None:
    """Return the matching route and captured path params, or ``None``."""
    for route, pattern in _COMPILED:
        if route.method != method:
            continue
        found = pattern.match(path)
        if found:
            return route, found.groupdict()
    return None


def build_event(
    method: str,
    path: str,
    *,
    headers: dict[str, str],
    body: str | None,
    query: dict[str, str] | None,
    path_params: dict[str, str],
) -> dict[str, Any]:
    """Build an HTTP API v2 event equivalent to what API Gateway would send."""
    route = match_route(method, path)
    route_key = route[0].route_key if route else f"{method} {path}"
    return {
        "version": "2.0",
        "routeKey": route_key,
        "rawPath": path,
        "headers": {k.lower(): v for k, v in headers.items()},
        "queryStringParameters": query or {},
        "pathParameters": path_params,
        "body": body,
        "isBase64Encoded": False,
        "requestContext": {
            "requestId": "local-" + str(threading.get_ident()),
            "http": {"method": method, "path": path},
        },
    }


class LocalApiServer:
    """A context-managed local server that invokes the real handlers.

    Optional fault modes (used by the sync end-to-end tests) short-circuit the
    handler dispatch without changing the authoritative ``ROUTES`` table:

    * ``fault_status`` returns that status with an error envelope for every
      request (e.g. 503), to drive the agent's transient-error path.
    * ``malformed`` returns a 200 whose body is not valid JSON, to drive the
      agent's malformed-response path.
    * ``redirect_to`` returns a 302 with that ``Location`` header, to drive the
      agent's redirect/CONFIG_ERROR path.

    ``request_count`` counts every request the server received.
    """

    def __init__(
        self,
        *,
        fault_status: int | None = None,
        malformed: bool = False,
        redirect_to: str | None = None,
    ) -> None:
        self.fault_status = fault_status
        self.malformed = malformed
        self.redirect_to = redirect_to
        self.request_count = 0
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._make_handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> LocalApiServer:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        server = self

        class _RequestHandler(BaseHTTPRequestHandler):
            def log_message(self, *_: Any) -> None:  # silence stderr noise
                return

            def _dispatch(inner, method: str) -> None:  # noqa: N805
                server.request_count += 1
                length = int(inner.headers.get("Content-Length", 0))
                body = (
                    inner.rfile.read(length).decode("utf-8") if length else None
                )
                if inner._apply_fault():
                    return
                raw_path, _, raw_query = inner.path.partition("?")
                matched = match_route(method, raw_path)
                query = _parse_query(raw_query)
                path_params = matched[1] if matched else {}
                handler = matched[0].handler if matched else None
                if handler is None:
                    inner._write(404, {"message": "Not Found"})
                    return
                event = build_event(
                    method,
                    raw_path,
                    headers=dict(inner.headers.items()),
                    body=body,
                    query=query,
                    path_params=path_params,
                )
                result = handler(event, None)
                status = int(result.get("statusCode", 500))
                payload = result.get("body", "")
                inner._write_raw(status, result.get("headers", {}), payload)

            def _apply_fault(inner) -> bool:  # noqa: N805
                """Apply a configured fault mode. Returns True when handled."""
                if server.redirect_to is not None:
                    inner._write_raw(
                        302, {"Location": server.redirect_to}, ""
                    )
                    return True
                if server.fault_status is not None:
                    inner._write(
                        server.fault_status,
                        {
                            "error": {
                                "code": "SERVICE_UNAVAILABLE",
                                "message": "simulated fault",
                            }
                        },
                    )
                    return True
                if server.malformed:
                    inner._write_raw(
                        200, {"Content-Type": "application/json"}, "{not json"
                    )
                    return True
                return False

            def _write(inner, status: int, body: Any) -> None:  # noqa: N805
                inner._write_raw(
                    status,
                    {"Content-Type": "application/json"},
                    json.dumps(body),
                )

            def _write_raw(  # noqa: N805
                inner, status: int, headers: dict[str, str], payload: str
            ) -> None:
                data = payload.encode("utf-8")
                inner.send_response(status)
                for key, value in headers.items():
                    inner.send_header(key, value)
                inner.send_header("Content-Length", str(len(data)))
                inner.end_headers()
                inner.wfile.write(data)

            def do_GET(inner) -> None:  # noqa: N802
                inner._dispatch("GET")

            def do_POST(inner) -> None:  # noqa: N802
                inner._dispatch("POST")

        return _RequestHandler


def _parse_query(raw_query: str) -> dict[str, str]:
    from urllib.parse import parse_qsl

    return dict(parse_qsl(raw_query))
