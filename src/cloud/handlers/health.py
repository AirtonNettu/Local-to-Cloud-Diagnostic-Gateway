"""Health handler: liveness only, no auth and no AWS calls (design B.11).

``GET /health`` returns 200 with a small status document. It touches no backing
dependency, so its IAM role carries logs permissions only and its
``REQUIRED_ENV`` is empty (``LOG_LEVEL``/``SERVICE_VERSION`` stay optional).
"""

from __future__ import annotations

from typing import Any

from cloud.config import CloudSettings
from cloud.handlers._support import configure_root_logging
from cloud.http import (
    Request,
    Response,
    RouteContext,
    api_handler,
    json_response,
    to_proxy_response,
)
from shared.utils.timeutil import to_iso, utc_now

__all__ = ["handler", "REQUIRED_ENV", "SERVICE"]

# Health needs no backing resource (finding F8).
REQUIRED_ENV: frozenset[str] = frozenset()
SERVICE = "diagnostic-gateway"
_FUNCTION = "health"


@api_handler(scope=None)
def _health(ctx: RouteContext) -> Response:
    return json_response(
        200,
        {
            "status": "ok",
            "service": SERVICE,
            "version": ctx.extra["version"],
            "time": to_iso(utc_now()),
        },
    )


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Lambda entry point for ``GET /health``."""
    settings = CloudSettings.load(required=REQUIRED_ENV)
    configure_root_logging(settings.log_level)
    request = Request.from_event(event)
    ctx = RouteContext(
        request=request,
        service=SERVICE,
        function=_FUNCTION,
        auth=None,
        extra={"version": settings.service_version},
    )
    return to_proxy_response(_health(ctx))
