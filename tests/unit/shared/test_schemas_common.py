"""Tests for the shared validation primitives and contract constants."""

from __future__ import annotations

from shared.schemas.common import (
    AGENT_VERSION_PATTERN,
    MAX_EVENT_BYTES,
    MAX_EVENTS_PER_REQUEST,
    MAX_REGISTRATION_BYTES,
    MAX_REQUEST_BYTES,
    check_bool,
    check_choice,
    check_int,
    check_number,
    check_pattern,
    check_string,
    require_field,
)


def test_contract_constants() -> None:
    assert MAX_EVENTS_PER_REQUEST == 10
    assert MAX_EVENT_BYTES == 32 * 1024
    assert MAX_REQUEST_BYTES == 256 * 1024
    assert MAX_REGISTRATION_BYTES == 8 * 1024


def test_agent_version_pattern() -> None:
    assert AGENT_VERSION_PATTERN.match("0.1.0")
    assert AGENT_VERSION_PATTERN.match("1.2.3-rc.1")
    assert not AGENT_VERSION_PATTERN.match("1.2")
    assert not AGENT_VERSION_PATTERN.match("v1.2.3")


def test_require_field() -> None:
    issues, present = require_field({"a": 1}, "a")
    assert present and issues == ()
    issues, present = require_field({}, "a")
    assert not present and issues[0].field == "a"


def test_check_string_bounds() -> None:
    assert check_string("abc", "f", min_len=1, max_len=5) == ()
    assert check_string("", "f", min_len=1)[0].field == "f"
    assert check_string("toolong", "f", max_len=3)[0].field == "f"
    assert check_string(123, "f")[0].message == "must be a string"


def test_check_int_rejects_bool() -> None:
    assert check_int(True, "f")[0].message == "must be an integer"
    assert check_int(5, "f", minimum=1, maximum=10) == ()
    assert check_int(0, "f", minimum=1)[0].field == "f"


def test_check_number_rejects_bool() -> None:
    assert check_number(False, "f")[0].message == "must be a number"
    assert check_number(1.5, "f", minimum=0.0, maximum=2.0) == ()


def test_check_bool() -> None:
    assert check_bool(True, "f") == ()
    assert check_bool(1, "f")[0].field == "f"


def test_check_pattern() -> None:
    assert check_pattern("0.1.0", "f", AGENT_VERSION_PATTERN) == ()
    assert check_pattern("bad", "f", AGENT_VERSION_PATTERN)[0].field == "f"


def test_check_choice() -> None:
    assert check_choice("a", "f", ("a", "b")) == ()
    assert check_choice("z", "f", ("a", "b"))[0].field == "f"
