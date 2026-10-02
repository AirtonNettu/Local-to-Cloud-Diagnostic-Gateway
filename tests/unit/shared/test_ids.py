"""Tests for UUIDv7 generation and validation."""

from __future__ import annotations

import uuid

from shared.utils.ids import is_uuid7, new_uuid7


def test_new_uuid7_is_valid_version_7() -> None:
    value = new_uuid7()
    parsed = uuid.UUID(value)
    assert parsed.version == 7
    assert (parsed.int >> 62) & 0b11 == 0b10  # RFC 4122 variant


def test_new_uuid7_is_time_ordered() -> None:
    earlier = new_uuid7(timestamp_ms=1_000)
    later = new_uuid7(timestamp_ms=2_000)
    assert earlier < later


def test_is_uuid7_accepts_generated_value() -> None:
    assert is_uuid7(new_uuid7())


def test_is_uuid7_rejects_uuid4() -> None:
    assert not is_uuid7(str(uuid.uuid4()))


def test_is_uuid7_rejects_garbage() -> None:
    assert not is_uuid7("not-a-uuid")
    assert not is_uuid7("")


def test_new_uuid7_values_are_unique() -> None:
    values = {new_uuid7(timestamp_ms=1_000) for _ in range(100)}
    assert len(values) == 100
