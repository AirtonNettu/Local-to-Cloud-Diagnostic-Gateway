"""Tests for the shared JSON logging formatter and redaction filter."""

from __future__ import annotations

import json
import logging

from shared.utils.json_logging import JsonFormatter, RedactionFilter, log_context


def _make_record(**extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="agent.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_formatter_emits_single_line_json() -> None:
    record = _make_record(event="unit_test", device_id="dev-1")
    line = JsonFormatter().format(record)
    assert "\n" not in line
    payload = json.loads(line)
    assert payload["message"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["component"] == "agent.test"
    assert payload["event"] == "unit_test"
    assert payload["device_id"] == "dev-1"


def test_formatter_ignores_non_whitelisted_extra() -> None:
    record = _make_record(event="e", some_random_field="should-not-appear")
    payload = json.loads(JsonFormatter().format(record))
    assert "some_random_field" not in payload


def test_redaction_filter_drops_secret_keys() -> None:
    record = _make_record(
        event="e",
        api_key="SECRET-VALUE",
        authorization="Bearer abc",
        password="hunter2",
        device_id="dev-1",
    )
    RedactionFilter().filter(record)
    assert not hasattr(record, "api_key")
    assert not hasattr(record, "authorization")
    assert not hasattr(record, "password")
    assert record.device_id == "dev-1"


def test_secret_value_never_appears_in_output() -> None:
    record = _make_record(event="e", token="SENTINEL-TOKEN-123")
    RedactionFilter().filter(record)
    line = JsonFormatter().format(record)
    assert "SENTINEL-TOKEN-123" not in line


def test_log_context_binds_whitelisted_fields() -> None:
    with log_context(request_id="req-9"):
        line = JsonFormatter().format(_make_record(event="e"))
    payload = json.loads(line)
    assert payload["request_id"] == "req-9"


def test_log_context_is_scoped() -> None:
    with log_context(request_id="req-9"):
        pass
    payload = json.loads(JsonFormatter().format(_make_record(event="e")))
    assert "request_id" not in payload


def test_timestamp_format() -> None:
    payload = json.loads(JsonFormatter().format(_make_record(event="e")))
    ts = payload["timestamp"]
    assert ts.endswith("Z")
    assert "T" in ts
