"""Opaque pagination cursors (design B.11).

A cursor is the base64url-encoded JSON of a DynamoDB ``LastEvaluatedKey``.
Decoding validates strictly so a tampered cursor can never read another
partition: any violation raises ``ValidationFailed`` with the ``INVALID_CURSOR``
code so the handler returns 400. Two key-set shapes are supported, matching the
device-list query (GSI1) and the per-device diagnostics query.
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any

from cloud.errors import ValidationFailed

__all__ = ["encode_cursor", "decode_device_cursor", "decode_diagnostic_cursor"]

_MAX_CURSOR_CHARS = 1024
_MAX_VALUE_CHARS = 128

_DEVICE_KEYS = frozenset({"PK", "SK", "GSI1PK", "GSI1SK"})
_DIAG_KEYS = frozenset({"PK", "SK"})


class InvalidCursor(ValidationFailed):
    """A cursor failed validation. Reported as 400 ``INVALID_CURSOR``."""

    code = "INVALID_CURSOR"

    def __init__(self, message: str = "Cursor is invalid.") -> None:
        super().__init__(message)


def encode_cursor(last_key: dict[str, Any]) -> str:
    """Encode a ``LastEvaluatedKey`` as a base64url cursor string."""
    raw = json.dumps(last_key, sort_keys=True, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def _decode_object(cursor: str) -> dict[str, Any]:
    if len(cursor) > _MAX_CURSOR_CHARS:
        raise InvalidCursor()
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        decoded = json.loads(raw.decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise InvalidCursor() from exc
    if not isinstance(decoded, dict):
        raise InvalidCursor()
    for value in decoded.values():
        if not isinstance(value, str) or len(value) > _MAX_VALUE_CHARS:
            raise InvalidCursor()
    return decoded


def decode_device_cursor(cursor: str) -> dict[str, Any]:
    """Decode and validate a device-list cursor (GSI1 key set)."""
    decoded = _decode_object(cursor)
    if set(decoded) != _DEVICE_KEYS:
        raise InvalidCursor()
    if decoded["GSI1PK"] != "DEVICE" or decoded["SK"] != "PROFILE":
        raise InvalidCursor()
    return decoded


def decode_diagnostic_cursor(cursor: str, *, device_id: str) -> dict[str, Any]:
    """Decode and validate a diagnostics cursor bound to ``device_id``.

    The ``PK`` must name the path device and the ``SK`` must stay inside the
    ``DIAG#`` range, so a cursor cannot be rewritten to page another device's
    partition.
    """
    decoded = _decode_object(cursor)
    if set(decoded) != _DIAG_KEYS:
        raise InvalidCursor()
    if decoded["PK"] != f"DEVICE#{device_id}":
        raise InvalidCursor()
    if not decoded["SK"].startswith("DIAG#"):
        raise InvalidCursor()
    return decoded
