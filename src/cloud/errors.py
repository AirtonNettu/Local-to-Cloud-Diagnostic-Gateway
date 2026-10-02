"""Cloud API error hierarchy (design B.11 / B.14).

Each ``ApiError`` carries the HTTP status, the error-envelope ``code`` and the
headers that the envelope requires (``WWW-Authenticate`` for 401, ``Retry-After``
for 503). ``@api_handler`` (``cloud/http.py``) maps each type to the status/code,
log level and metric of the B.14 table; raising one of these is how a route
reports a client- or dependency-level failure.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

__all__ = [
    "ApiError",
    "InvalidJsonError",
    "ValidationFailed",
    "PayloadTooLarge",
    "Unauthorized",
    "Forbidden",
    "NotFound",
    "DeviceNotRegistered",
    "DependencyUnavailable",
]


class ApiError(Exception):
    """Base class for every error that maps to a JSON error envelope.

    ``details`` is a list of ``{"field", "issue"}`` dicts, capped by the caller
    to the documented limit. ``extra_headers`` lets subclasses add headers such
    as ``WWW-Authenticate`` without the handler special-casing them.
    """

    status: int = 500
    code: str = "INTERNAL_ERROR"

    def __init__(
        self,
        message: str,
        *,
        details: Sequence[Mapping[str, str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details: list[dict[str, str]] = [dict(d) for d in (details or [])]

    def extra_headers(self) -> dict[str, str]:
        """Return headers the envelope requires for this error (default none)."""
        return {}

    def to_envelope(self, request_id: str) -> dict[str, Any]:
        """Render the error envelope body (``details`` already capped)."""
        error: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "request_id": request_id,
        }
        if self.details:
            error["details"] = self.details
        return {"error": error}


class InvalidJsonError(ApiError):
    """The request body is not valid JSON."""

    status = 400
    code = "INVALID_JSON"

    def __init__(self, message: str = "Request body is not valid JSON.") -> None:
        super().__init__(message)


class ValidationFailed(ApiError):
    """One or more fields failed validation (field names only, never values)."""

    status = 400
    code = "VALIDATION_ERROR"

    def __init__(
        self,
        message: str = "Request validation failed.",
        *,
        details: Sequence[Mapping[str, str]] | None = None,
    ) -> None:
        super().__init__(message, details=details)


class PayloadTooLarge(ApiError):
    """The decoded request body exceeds the per-endpoint byte limit."""

    status = 413
    code = "PAYLOAD_TOO_LARGE"

    def __init__(self, message: str = "Request body is too large.") -> None:
        super().__init__(message)


class Unauthorized(ApiError):
    """Missing or invalid credentials. Carries ``WWW-Authenticate: Bearer``."""

    status = 401
    code = "UNAUTHORIZED"

    def __init__(self, message: str = "Authentication is required.") -> None:
        super().__init__(message)

    def extra_headers(self) -> dict[str, str]:
        return {"WWW-Authenticate": "Bearer"}


class Forbidden(ApiError):
    """A valid key with the wrong scope."""

    status = 403
    code = "FORBIDDEN"

    def __init__(self, message: str = "This key is not allowed on this route.") -> None:
        super().__init__(message)


class NotFound(ApiError):
    """A requested resource does not exist."""

    status = 404
    code = "NOT_FOUND"

    def __init__(self, message: str = "Resource not found.") -> None:
        super().__init__(message)


class DeviceNotRegistered(ApiError):
    """Telemetry references a device that has not been registered."""

    status = 409
    code = "DEVICE_NOT_REGISTERED"

    def __init__(self, message: str = "Device is not registered.") -> None:
        super().__init__(message)


class DependencyUnavailable(ApiError):
    """A backing dependency (SSM/DynamoDB) is unavailable. Carries Retry-After."""

    status = 503
    code = "SERVICE_UNAVAILABLE"

    def __init__(self, message: str = "Service temporarily unavailable.") -> None:
        super().__init__(message)

    def extra_headers(self) -> dict[str, str]:
        return {"Retry-After": "5"}
