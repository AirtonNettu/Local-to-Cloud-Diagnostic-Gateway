"""Structured JSON logging shared by the agent and the cloud backend.

Provides a ``JsonFormatter`` that emits one JSON object per line, a redaction
filter that drops any secret-looking extra key, and a ``contextvars``-based
``log_context`` helper for binding fields (such as ``device_id`` or
``request_id``) to a scope. No secret value may ever reach the log.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

__all__ = ["JsonFormatter", "RedactionFilter", "log_context", "bind_context"]

# Extra keys matching this pattern are dropped before serialization.
_SECRET_KEY_PATTERN = re.compile(r"(?i)key|token|secret|password|authorization")

# Only these context/extra keys are serialized; anything else from ``extra`` is
# ignored so logs cannot accidentally carry arbitrary data.
_WHITELISTED_KEYS = (
    "device_id",
    "request_id",
    "run_id",
    "event_id",
    "error",
    "error_type",
    "http_status",
    "duration_ms",
    "count",
    "scenario",
    "component",
)

# Standard LogRecord attributes we never copy from ``extra``.
_RESERVED_RECORD_KEYS = frozenset(
    logging.makeLogRecord({}).__dict__.keys()
) | {"message", "asctime", "event"}

_MAX_REPR_CHARS = 200

_log_context: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "log_context", default=None
)


def _current_context() -> dict[str, Any]:
    return _log_context.get() or {}


def _safe_value(value: Any) -> Any:
    """Return a JSON-serializable representation, never a raw arbitrary object."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    text = repr(value)
    if len(text) > _MAX_REPR_CHARS:
        text = text[:_MAX_REPR_CHARS] + "..."
    return text


class RedactionFilter(logging.Filter):
    """Drop secret-looking keys from a record's extra attributes."""

    def filter(self, record: logging.LogRecord) -> bool:
        for key in list(record.__dict__.keys()):
            if key not in _RESERVED_RECORD_KEYS and _SECRET_KEY_PATTERN.search(key):
                del record.__dict__[key]
        return True


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, tz=UTC)
        payload: dict[str, Any] = {
            "timestamp": _format_timestamp(timestamp),
            "level": record.levelname,
            "component": record.name,
            "event": getattr(record, "event", None),
            "message": record.getMessage(),
        }

        bound = _current_context()
        for key, value in bound.items():
            if key in _WHITELISTED_KEYS and not _SECRET_KEY_PATTERN.search(key):
                payload[key] = _safe_value(value)

        for key in _WHITELISTED_KEYS:
            if key in record.__dict__ and not _SECRET_KEY_PATTERN.search(key):
                payload[key] = _safe_value(record.__dict__[key])

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        # Drop keys whose value is None to keep lines compact, except message.
        compact = {k: v for k, v in payload.items() if v is not None or k == "message"}
        return json.dumps(compact, ensure_ascii=False, separators=(",", ":"))


def _format_timestamp(value: datetime) -> str:
    millis = value.microsecond // 1000
    return (
        f"{value.year:04d}-{value.month:02d}-{value.day:02d}"
        f"T{value.hour:02d}:{value.minute:02d}:{value.second:02d}.{millis:03d}Z"
    )


def bind_context(**fields: Any) -> contextvars.Token[dict[str, Any] | None]:
    """Bind context fields, returning a token the caller can reset."""
    current = dict(_current_context())
    current.update(fields)
    return _log_context.set(current)


@contextmanager
def log_context(**fields: Any) -> Iterator[None]:
    """Bind context fields for the duration of the ``with`` block."""
    token = bind_context(**fields)
    try:
        yield
    finally:
        _log_context.reset(token)
