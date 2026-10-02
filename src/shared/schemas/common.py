"""Validation primitives and contract constants shared by both sides.

``ValidationIssue`` accumulates per-field problems; the field helpers return a
tuple of issues so a validator can report every problem at once rather than
failing on the first. The size limits are the contract between the agent's
batch packer and the cloud's request guard, so both import them from here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

__all__ = [
    "ValidationIssue",
    "MAX_EVENTS_PER_REQUEST",
    "MAX_EVENT_BYTES",
    "MAX_REQUEST_BYTES",
    "MAX_REGISTRATION_BYTES",
    "MAX_CLOCK_SKEW_SECONDS",
    "AGENT_VERSION_PATTERN",
    "DEVICE_ID_PATTERN",
    "require_field",
    "check_string",
    "check_int",
    "check_number",
    "check_bool",
    "check_pattern",
    "check_choice",
]

# --- Contract constants (not configuration) ----------------------------------
MAX_EVENTS_PER_REQUEST = 10
MAX_EVENT_BYTES = 32 * 1024  # serialized compact JSON of one event
MAX_REQUEST_BYTES = 256 * 1024  # decoded telemetry request body
MAX_REGISTRATION_BYTES = 8 * 1024  # POST /v1/devices body
MAX_CLOCK_SKEW_SECONDS = 300  # accepted drift between agent and server

# Semantic version with an optional pre-release/build suffix (see review NIT9).
AGENT_VERSION_PATTERN = re.compile(
    r"^\d{1,4}\.\d{1,4}\.\d{1,4}(?:[-+][0-9A-Za-z.-]{1,20})?$"
)
DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


@dataclass(frozen=True)
class ValidationIssue:
    """A single validation problem: which field, and what is wrong."""

    field: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"field": self.field, "message": self.message}


# ``bool`` is an ``int`` subclass, so numeric checks must reject it explicitly.
def _is_real_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def require_field(
    data: dict[str, Any], field: str
) -> tuple[tuple[ValidationIssue, ...], bool]:
    """Return (issues, present). ``present`` is False when the key is missing."""
    if field not in data:
        return (ValidationIssue(field, "is required"),), False
    return (), True


def check_string(
    value: Any,
    field: str,
    *,
    min_len: int = 0,
    max_len: int | None = None,
) -> tuple[ValidationIssue, ...]:
    if not isinstance(value, str):
        return (ValidationIssue(field, "must be a string"),)
    issues: list[ValidationIssue] = []
    if len(value) < min_len:
        issues.append(
            ValidationIssue(field, f"must have at least {min_len} characters")
        )
    if max_len is not None and len(value) > max_len:
        issues.append(
            ValidationIssue(field, f"must have at most {max_len} characters")
        )
    return tuple(issues)


def check_int(
    value: Any,
    field: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> tuple[ValidationIssue, ...]:
    if not _is_real_int(value):
        return (ValidationIssue(field, "must be an integer"),)
    issues: list[ValidationIssue] = []
    if minimum is not None and value < minimum:
        issues.append(ValidationIssue(field, f"must be >= {minimum}"))
    if maximum is not None and value > maximum:
        issues.append(ValidationIssue(field, f"must be <= {maximum}"))
    return tuple(issues)


def check_number(
    value: Any,
    field: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> tuple[ValidationIssue, ...]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return (ValidationIssue(field, "must be a number"),)
    issues: list[ValidationIssue] = []
    if minimum is not None and value < minimum:
        issues.append(ValidationIssue(field, f"must be >= {minimum}"))
    if maximum is not None and value > maximum:
        issues.append(ValidationIssue(field, f"must be <= {maximum}"))
    return tuple(issues)


def check_bool(value: Any, field: str) -> tuple[ValidationIssue, ...]:
    if not isinstance(value, bool):
        return (ValidationIssue(field, "must be a boolean"),)
    return ()


def check_pattern(
    value: Any, field: str, pattern: re.Pattern[str]
) -> tuple[ValidationIssue, ...]:
    if not isinstance(value, str):
        return (ValidationIssue(field, "must be a string"),)
    if not pattern.match(value):
        return (ValidationIssue(field, "has an invalid format"),)
    return ()


def check_choice(
    value: Any, field: str, choices: tuple[Any, ...]
) -> tuple[ValidationIssue, ...]:
    if value not in choices:
        allowed = ", ".join(str(c) for c in choices)
        return (ValidationIssue(field, f"must be one of: {allowed}"),)
    return ()
