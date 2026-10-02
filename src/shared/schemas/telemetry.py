"""Telemetry validators (the ``POST /v1/telemetry`` contract, §B.11).

Two entry points:

* ``validate_telemetry_envelope`` checks the request wrapper (``schema_version``,
  ``device_id`` and the ``events`` list cardinality). Any problem rejects the
  whole request with a 400.
* ``validate_event`` checks one event and returns ``(code, issues)``. ``code`` is
  ``None`` when the event is valid, ``"CLOCK_SKEW"`` when the timestamp is more
  than ``MAX_CLOCK_SKEW_SECONDS`` in the future, else ``"VALIDATION_ERROR"``. The
  future-timestamp check runs first, so a skewed-but-otherwise-invalid event is
  reported as ``CLOCK_SKEW`` (deterministic precedence) and retried.

The agent pre-checks every event it builds with the same code the cloud
enforces, so a contract test proves agent output is always acceptable.
"""

from __future__ import annotations

import json
import re
from datetime import timedelta
from typing import Any

from shared.models.diagnostic import (
    CheckStatus,
    HealthStatus,
    NetworkStatus,
    Severity,
)
from shared.schemas.common import (
    DEVICE_ID_PATTERN,
    MAX_CLOCK_SKEW_SECONDS,
    MAX_EVENT_BYTES,
    MAX_EVENTS_PER_REQUEST,
    ValidationIssue,
    check_choice,
    check_number,
    check_string,
    require_field,
)
from shared.utils.timeutil import parse_iso, utc_now

__all__ = [
    "validate_telemetry_envelope",
    "validate_event",
]

_MAX_PAST_DAYS = 365

_CHECK_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")
_RULE_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
_METRIC_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")
_LABEL_KEY_PATTERN = re.compile(r"^[a-z_]{1,32}$")

_METRIC_UNITS = ("percent", "bytes", "ms", "count", "seconds", "mhz")

_EVENT_FIELDS = frozenset(
    {
        "event_id",
        "event_type",
        "schema_version",
        "timestamp",
        "source",
        "status",
        "network_status",
        "checks",
        "alerts",
        "metrics",
    }
)
_CHECK_FIELDS = frozenset({"name", "status", "summary", "evidence"})
_ALERT_FIELDS = frozenset({"rule_id", "severity", "message", "subject"})
_METRIC_FIELDS = frozenset({"name", "value", "unit", "labels"})

_HEALTH_VALUES = tuple(s.value for s in HealthStatus)
_NETWORK_VALUES = tuple(s.value for s in NetworkStatus)
_CHECK_STATUS_VALUES = tuple(s.value for s in CheckStatus)
_SEVERITY_VALUES = tuple(s.value for s in Severity)


def _reject_unknown(
    data: dict[str, Any], allowed: frozenset[str], prefix: str
) -> list[ValidationIssue]:
    return [
        ValidationIssue(f"{prefix}{key}", "is not an allowed field")
        for key in data
        if key not in allowed
    ]


def validate_telemetry_envelope(data: Any) -> list[ValidationIssue]:
    """Return envelope-level problems (not per-event). Empty means valid."""
    if not isinstance(data, dict):
        return [ValidationIssue("", "must be a JSON object")]

    issues: list[ValidationIssue] = []
    issues.extend(_reject_unknown(data, frozenset({"schema_version", "device_id",
                                                    "events"}), ""))

    schema_issues, present = require_field(data, "schema_version")
    issues.extend(schema_issues)
    if present:
        value = data["schema_version"]
        if isinstance(value, bool) or value != 1:
            issues.append(ValidationIssue("schema_version", "must equal 1"))

    id_issues, present = require_field(data, "device_id")
    issues.extend(id_issues)
    if present:
        from shared.schemas.common import check_pattern

        issues.extend(check_pattern(data["device_id"], "device_id", DEVICE_ID_PATTERN))

    events_issues, present = require_field(data, "events")
    issues.extend(events_issues)
    if present:
        events = data["events"]
        if not isinstance(events, list):
            issues.append(ValidationIssue("events", "must be a list"))
        elif not (1 <= len(events) <= MAX_EVENTS_PER_REQUEST):
            issues.append(
                ValidationIssue(
                    "events", f"must contain 1 to {MAX_EVENTS_PER_REQUEST} events"
                )
            )
    return issues


def _timestamp_code(event: dict[str, Any]) -> str | None:
    """Return ``"CLOCK_SKEW"`` if the timestamp is too far in the future.

    Checked before any other per-event rule (deterministic precedence). A
    missing or unparsable timestamp is not a clock skew; it falls through to
    ``VALIDATION_ERROR`` in the main validator.
    """
    raw = event.get("timestamp")
    if not isinstance(raw, str):
        return None
    try:
        parsed = parse_iso(raw)
    except ValueError:
        return None
    now = utc_now()
    if parsed - now > timedelta(seconds=MAX_CLOCK_SKEW_SECONDS):
        return "CLOCK_SKEW"
    return None


def validate_event(event: Any) -> tuple[str | None, list[ValidationIssue]]:
    """Validate one event. Returns ``(code, issues)``.

    ``code`` is ``None`` (valid), ``"CLOCK_SKEW"`` (future timestamp), or
    ``"VALIDATION_ERROR"`` (any other problem). The clock-skew check wins over
    every other issue for the same event.
    """
    if not isinstance(event, dict):
        return "VALIDATION_ERROR", [ValidationIssue("", "must be a JSON object")]

    if _timestamp_code(event) == "CLOCK_SKEW":
        return "CLOCK_SKEW", [
            ValidationIssue(
                "timestamp",
                f"more than {MAX_CLOCK_SKEW_SECONDS} s in the future",
            )
        ]

    issues = _validate_event_fields(event)
    size_issue = _event_size_issue(event)
    if size_issue is not None:
        issues.append(size_issue)
    if issues:
        return "VALIDATION_ERROR", issues
    return None, []


def _event_size_issue(event: dict[str, Any]) -> ValidationIssue | None:
    try:
        encoded = json.dumps(event, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError):
        return None  # non-serializable content is reported by field checks
    if len(encoded) > MAX_EVENT_BYTES:
        return ValidationIssue("", f"serialized event exceeds {MAX_EVENT_BYTES} bytes")
    return None


def _validate_event_fields(event: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    issues.extend(_reject_unknown(event, _EVENT_FIELDS, ""))

    issues.extend(_require_pattern_uuid7(event))

    issues.extend(_require_equal(event, "event_type", "diagnostic_run"))

    schema_issues, present = require_field(event, "schema_version")
    issues.extend(schema_issues)
    if present and (isinstance(event["schema_version"], bool)
                    or event["schema_version"] != 1):
        issues.append(ValidationIssue("schema_version", "must equal 1"))

    issues.extend(_validate_timestamp(event))

    issues.extend(_require_choice(event, "source", ("live", "demo")))
    issues.extend(_require_choice(event, "status", _HEALTH_VALUES))
    issues.extend(_require_choice(event, "network_status", _NETWORK_VALUES))

    issues.extend(_validate_checks(event))
    issues.extend(_validate_alerts(event))
    issues.extend(_validate_metrics(event))
    return issues


def _require_pattern_uuid7(event: dict[str, Any]) -> list[ValidationIssue]:
    from shared.utils.ids import is_uuid7

    field_issues, present = require_field(event, "event_id")
    out = list(field_issues)
    if present and not (isinstance(event["event_id"], str)
                        and is_uuid7(event["event_id"])):
        out.append(ValidationIssue("event_id", "must be a UUIDv7"))
    return out


def _require_equal(
    data: dict[str, Any], field: str, expected: str
) -> list[ValidationIssue]:
    field_issues, present = require_field(data, field)
    out = list(field_issues)
    if present and data[field] != expected:
        out.append(ValidationIssue(field, f"must equal {expected!r}"))
    return out


def _require_choice(
    data: dict[str, Any], field: str, choices: tuple[Any, ...]
) -> list[ValidationIssue]:
    field_issues, present = require_field(data, field)
    out = list(field_issues)
    if present:
        out.extend(check_choice(data[field], field, choices))
    return out


def _validate_timestamp(event: dict[str, Any]) -> list[ValidationIssue]:
    field_issues, present = require_field(event, "timestamp")
    if not present:
        return list(field_issues)
    raw = event["timestamp"]
    if not isinstance(raw, str):
        return [ValidationIssue("timestamp", "must be a string")]
    try:
        parsed = parse_iso(raw)
    except ValueError:
        return [ValidationIssue("timestamp", "must be ISO 8601 UTC")]
    now = utc_now()
    if now - parsed > timedelta(days=_MAX_PAST_DAYS):
        return [ValidationIssue("timestamp", f"older than {_MAX_PAST_DAYS} days")]
    return []


def _validate_checks(event: dict[str, Any]) -> list[ValidationIssue]:
    checks = event.get("checks")
    if checks is None:
        return [ValidationIssue("checks", "is required")]
    if not isinstance(checks, list):
        return [ValidationIssue("checks", "must be a list")]
    if len(checks) > 50:
        return [ValidationIssue("checks", "must contain at most 50 items")]
    issues: list[ValidationIssue] = []
    for index, check in enumerate(checks):
        prefix = f"checks[{index}]"
        if not isinstance(check, dict):
            issues.append(ValidationIssue(prefix, "must be a JSON object"))
            continue
        issues.extend(_reject_unknown(check, _CHECK_FIELDS, f"{prefix}."))
        issues.extend(_pattern_field(check, "name", prefix, _CHECK_NAME_PATTERN))
        issues.extend(_choice_field(check, "status", prefix, _CHECK_STATUS_VALUES))
        issues.extend(_string_field(check, "summary", prefix, max_len=256))
        issues.extend(_evidence(check, prefix))
    return issues


def _evidence(check: dict[str, Any], prefix: str) -> list[ValidationIssue]:
    field_issues, present = require_field(check, "evidence")
    if not present:
        return [ValidationIssue(f"{prefix}.evidence", i.message) for i in field_issues]
    evidence = check["evidence"]
    if not isinstance(evidence, list):
        return [ValidationIssue(f"{prefix}.evidence", "must be a list")]
    if len(evidence) > 10:
        return [ValidationIssue(f"{prefix}.evidence", "must contain at most 10 items")]
    out: list[ValidationIssue] = []
    for index, item in enumerate(evidence):
        out.extend(
            check_string(item, f"{prefix}.evidence[{index}]", min_len=0, max_len=256)
        )
    return out


def _validate_alerts(event: dict[str, Any]) -> list[ValidationIssue]:
    alerts = event.get("alerts")
    if alerts is None:
        return [ValidationIssue("alerts", "is required")]
    if not isinstance(alerts, list):
        return [ValidationIssue("alerts", "must be a list")]
    if len(alerts) > 50:
        return [ValidationIssue("alerts", "must contain at most 50 items")]
    issues: list[ValidationIssue] = []
    for index, alert in enumerate(alerts):
        prefix = f"alerts[{index}]"
        if not isinstance(alert, dict):
            issues.append(ValidationIssue(prefix, "must be a JSON object"))
            continue
        issues.extend(_reject_unknown(alert, _ALERT_FIELDS, f"{prefix}."))
        issues.extend(_pattern_field(alert, "rule_id", prefix, _RULE_ID_PATTERN))
        issues.extend(_choice_field(alert, "severity", prefix, _SEVERITY_VALUES))
        issues.extend(_string_field(alert, "message", prefix, max_len=512))
        subject = alert.get("subject")
        if subject is not None:
            issues.extend(
                check_string(subject, f"{prefix}.subject", min_len=0, max_len=64)
            )
    return issues


def _validate_metrics(event: dict[str, Any]) -> list[ValidationIssue]:
    metrics = event.get("metrics")
    if metrics is None:
        return [ValidationIssue("metrics", "is required")]
    if not isinstance(metrics, list):
        return [ValidationIssue("metrics", "must be a list")]
    if len(metrics) > 100:
        return [ValidationIssue("metrics", "must contain at most 100 items")]
    issues: list[ValidationIssue] = []
    for index, metric in enumerate(metrics):
        prefix = f"metrics[{index}]"
        if not isinstance(metric, dict):
            issues.append(ValidationIssue(prefix, "must be a JSON object"))
            continue
        issues.extend(_reject_unknown(metric, _METRIC_FIELDS, f"{prefix}."))
        issues.extend(_pattern_field(metric, "name", prefix, _METRIC_NAME_PATTERN))
        issues.extend(_metric_value(metric, prefix))
        issues.extend(_choice_field(metric, "unit", prefix, _METRIC_UNITS))
        issues.extend(_metric_labels(metric, prefix))
    return issues


def _metric_value(metric: dict[str, Any], prefix: str) -> list[ValidationIssue]:
    field_issues, present = require_field(metric, "value")
    if not present:
        return [ValidationIssue(f"{prefix}.value", i.message) for i in field_issues]
    value = metric["value"]
    issues = list(check_number(value, f"{prefix}.value"))
    if not issues and isinstance(value, float) and value != value:  # NaN
        issues.append(ValidationIssue(f"{prefix}.value", "must be finite"))
    if (
        not issues
        and isinstance(value, float)
        and (value == float("inf") or value == float("-inf"))
    ):
        issues.append(ValidationIssue(f"{prefix}.value", "must be finite"))
    return issues


def _metric_labels(metric: dict[str, Any], prefix: str) -> list[ValidationIssue]:
    labels = metric.get("labels", {})
    if not isinstance(labels, dict):
        return [ValidationIssue(f"{prefix}.labels", "must be a JSON object")]
    if len(labels) > 4:
        return [ValidationIssue(f"{prefix}.labels", "must contain at most 4 pairs")]
    out: list[ValidationIssue] = []
    for key, value in labels.items():
        if not (isinstance(key, str) and _LABEL_KEY_PATTERN.match(key)):
            out.append(
                ValidationIssue(f"{prefix}.labels", f"invalid label key {key!r}")
            )
        out.extend(
            check_string(value, f"{prefix}.labels.{key}", min_len=0, max_len=64)
        )
    return out


def _pattern_field(
    data: dict[str, Any], field: str, prefix: str, pattern: re.Pattern[str]
) -> list[ValidationIssue]:
    from shared.schemas.common import check_pattern

    field_issues, present = require_field(data, field)
    if not present:
        return [ValidationIssue(f"{prefix}.{field}", i.message) for i in field_issues]
    return list(check_pattern(data[field], f"{prefix}.{field}", pattern))


def _choice_field(
    data: dict[str, Any], field: str, prefix: str, choices: tuple[Any, ...]
) -> list[ValidationIssue]:
    field_issues, present = require_field(data, field)
    if not present:
        return [ValidationIssue(f"{prefix}.{field}", i.message) for i in field_issues]
    return list(check_choice(data[field], f"{prefix}.{field}", choices))


def _string_field(
    data: dict[str, Any], field: str, prefix: str, *, max_len: int
) -> list[ValidationIssue]:
    field_issues, present = require_field(data, field)
    if not present:
        return [ValidationIssue(f"{prefix}.{field}", i.message) for i in field_issues]
    return list(check_string(data[field], f"{prefix}.{field}", min_len=0,
                             max_len=max_len))
