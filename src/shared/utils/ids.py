"""UUIDv7 generation and validation (RFC 9562).

Python only ships ``uuid.uuid7`` from 3.14 onwards, and the Lambda runtime is
3.13, so a small, self-contained implementation is provided here. UUIDv7 is
time-ordered: the first 48 bits are a Unix timestamp in milliseconds, which the
DynamoDB sort key exploits for naturally ordered reads.
"""

from __future__ import annotations

import secrets
import time
import uuid

__all__ = ["new_uuid7", "is_uuid7"]

# RFC 9562 layout constants.
_VERSION_7 = 0x7000  # version nibble in the time_hi_and_version field
_VARIANT_RFC4122 = 0x8000  # the top two bits of clock_seq_hi are '10'
_VARIANT_MASK = 0xC000


def new_uuid7(*, timestamp_ms: int | None = None) -> str:
    """Return a new UUIDv7 as a canonical lowercase string.

    ``timestamp_ms`` may be supplied for deterministic tests; otherwise the
    current wall-clock time in milliseconds is used.
    """
    if timestamp_ms is None:
        timestamp_ms = time.time_ns() // 1_000_000
    # 48-bit timestamp; mask to stay within range even far in the future.
    ts = timestamp_ms & 0xFFFFFFFFFFFF

    # 74 random bits total: 12 in rand_a, 62 in rand_b. secrets gives us CSPRNG.
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)

    # Assemble the 128-bit integer field by field (big-endian).
    value = ts << 80
    value |= _VERSION_7 << 64
    value |= rand_a << 64
    # Variant bits occupy the top two bits of the 64-bit low half.
    low = (_VARIANT_RFC4122 << 48) | rand_b
    value |= low
    return str(uuid.UUID(int=value))


def is_uuid7(value: str) -> bool:
    """Return True if ``value`` is a well-formed UUID with version nibble 7."""
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    if parsed.version != 7:
        return False
    # Validate the RFC 4122 variant bits as well.
    return (parsed.int >> 62) & 0b11 == 0b10
