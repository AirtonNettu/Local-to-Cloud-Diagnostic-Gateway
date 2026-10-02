"""Cursor encode/decode and the strict key-set/tamper rules (design B.11)."""

from __future__ import annotations

import base64
import json

import pytest

from cloud.cursor import (
    decode_device_cursor,
    decode_diagnostic_cursor,
    encode_cursor,
)
from cloud.errors import ValidationFailed


def _cursor(obj: dict) -> str:
    return base64.urlsafe_b64encode(
        json.dumps(obj).encode("utf-8")
    ).decode("ascii")


def test_device_cursor_round_trip() -> None:
    key = {
        "PK": "DEVICE#d1",
        "SK": "PROFILE",
        "GSI1PK": "DEVICE",
        "GSI1SK": "DEVICE#d1",
    }
    encoded = encode_cursor(key)
    assert decode_device_cursor(encoded) == key


def test_diagnostic_cursor_round_trip() -> None:
    key = {"PK": "DEVICE#d1", "SK": "DIAG#01923c5e"}
    encoded = encode_cursor(key)
    assert decode_diagnostic_cursor(encoded, device_id="d1") == key


def test_invalid_base64_rejected() -> None:
    with pytest.raises(ValidationFailed) as info:
        decode_device_cursor("!!!not-base64!!!")
    assert info.value.code == "INVALID_CURSOR"


def test_non_object_rejected() -> None:
    with pytest.raises(ValidationFailed):
        decode_device_cursor(_cursor([1, 2, 3]))  # type: ignore[arg-type]


def test_non_string_value_rejected() -> None:
    with pytest.raises(ValidationFailed):
        decode_device_cursor(
            _cursor({"PK": 1, "SK": "PROFILE", "GSI1PK": "DEVICE", "GSI1SK": "x"})
        )


def test_oversized_value_rejected() -> None:
    with pytest.raises(ValidationFailed):
        decode_device_cursor(
            _cursor(
                {
                    "PK": "x" * 200,
                    "SK": "PROFILE",
                    "GSI1PK": "DEVICE",
                    "GSI1SK": "y",
                }
            )
        )


def test_device_cursor_wrong_key_set_rejected() -> None:
    with pytest.raises(ValidationFailed):
        decode_device_cursor(_cursor({"PK": "DEVICE#d1", "SK": "PROFILE"}))


def test_device_cursor_tampered_gsi1pk_rejected() -> None:
    with pytest.raises(ValidationFailed):
        decode_device_cursor(
            _cursor(
                {
                    "PK": "DEVICE#d1",
                    "SK": "PROFILE",
                    "GSI1PK": "OTHER",
                    "GSI1SK": "DEVICE#d1",
                }
            )
        )


def test_diagnostic_cursor_cross_device_rejected() -> None:
    # A cursor minted for d1 cannot be used to page d2's partition.
    with pytest.raises(ValidationFailed):
        decode_diagnostic_cursor(
            _cursor({"PK": "DEVICE#d1", "SK": "DIAG#x"}), device_id="d2"
        )


def test_diagnostic_cursor_wrong_sk_prefix_rejected() -> None:
    with pytest.raises(ValidationFailed):
        decode_diagnostic_cursor(
            _cursor({"PK": "DEVICE#d1", "SK": "PROFILE"}), device_id="d1"
        )


def test_oversized_cursor_rejected() -> None:
    with pytest.raises(ValidationFailed):
        decode_device_cursor("a" * 2000)
