"""Timestamp helpers. All timestamps are ISO 8601 UTC with milliseconds and Z.

Naive datetimes (without tzinfo) are rejected everywhere so a local-time value
can never silently be treated as UTC.
"""

from __future__ import annotations

from datetime import UTC, datetime

__all__ = ["utc_now", "to_iso", "parse_iso"]


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


def to_iso(value: datetime) -> str:
    """Serialize a timezone-aware datetime to ISO 8601 UTC with ms and 'Z'.

    Example: ``2024-01-02T03:04:05.678Z``. Raises ``ValueError`` for naive
    datetimes.
    """
    if value.tzinfo is None:
        raise ValueError("naive datetime is not allowed; attach a UTC tzinfo")
    utc_value = value.astimezone(UTC)
    # Millisecond precision: microseconds // 1000.
    millis = utc_value.microsecond // 1000
    return (
        f"{utc_value.year:04d}-{utc_value.month:02d}-{utc_value.day:02d}"
        f"T{utc_value.hour:02d}:{utc_value.minute:02d}:{utc_value.second:02d}"
        f".{millis:03d}Z"
    )


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 timestamp into a timezone-aware UTC datetime.

    Accepts a trailing ``Z`` as well as explicit offsets. Raises ``ValueError``
    for malformed input or a value that carries no timezone (naive).
    """
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    normalized = value.strip()
    if normalized.endswith(("Z", "z")):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("naive datetime is not allowed; a timezone is required")
    return parsed.astimezone(UTC)
