"""Tests for timestamp helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from shared.utils.timeutil import parse_iso, to_iso, utc_now


def test_utc_now_is_timezone_aware() -> None:
    assert utc_now().tzinfo is not None


def test_to_iso_formats_with_millis_and_z() -> None:
    moment = datetime(2024, 1, 2, 3, 4, 5, 678901, tzinfo=UTC)
    assert to_iso(moment) == "2024-01-02T03:04:05.678Z"


def test_to_iso_rejects_naive() -> None:
    with pytest.raises(ValueError):
        to_iso(datetime(2024, 1, 2, 3, 4, 5))


def test_to_iso_converts_offset_to_utc() -> None:
    moment = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone(timedelta(hours=2)))
    assert to_iso(moment) == "2024-01-02T01:04:05.000Z"


def test_parse_iso_accepts_z_suffix() -> None:
    parsed = parse_iso("2024-01-02T03:04:05.678Z")
    assert parsed.tzinfo is not None
    assert to_iso(parsed) == "2024-01-02T03:04:05.678Z"


def test_parse_iso_rejects_naive() -> None:
    with pytest.raises(ValueError):
        parse_iso("2024-01-02T03:04:05")


def test_parse_iso_round_trip() -> None:
    original = utc_now()
    assert to_iso(parse_iso(to_iso(original))) == to_iso(original)
