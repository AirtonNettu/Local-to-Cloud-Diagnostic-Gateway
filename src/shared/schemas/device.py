"""Device-registration validator (the ``POST /v1/devices`` contract).

``validate_device_registration`` enforces the §B.11 rules. The cloud enforces
them on every request and the agent pre-checks the payload it builds with the
same code, so a contract test proves the agent's output is always acceptable to
the backend. Every problem is reported at once (never fail-fast) and unknown
top-level fields are rejected so the schema cannot drift silently.
"""

from __future__ import annotations

from typing import Any

from shared.schemas.common import (
    AGENT_VERSION_PATTERN,
    DEVICE_ID_PATTERN,
    ValidationIssue,
    check_int,
    check_pattern,
    check_string,
    require_field,
)

__all__ = ["validate_device_registration"]

_TOP_LEVEL_FIELDS = frozenset(
    {"schema_version", "device_id", "device_name", "os", "hardware", "agent_version"}
)
_OS_FIELDS = frozenset({"name", "version", "architecture"})
_HARDWARE_FIELDS = frozenset(
    {"cpu_model", "logical_cpus", "physical_cores", "memory_total_bytes"}
)

_MAX_MEMORY_BYTES = 2**50


def _reject_unknown(
    data: dict[str, Any], allowed: frozenset[str], prefix: str
) -> list[ValidationIssue]:
    return [
        ValidationIssue(f"{prefix}{key}", "is not an allowed field")
        for key in data
        if key not in allowed
    ]


def _control_free(value: str) -> bool:
    return all(ord(ch) >= 0x20 and ch != "\x7f" for ch in value)


def validate_device_registration(data: Any) -> list[ValidationIssue]:
    """Return every validation problem for a device-registration payload.

    An empty list means the payload is valid.
    """
    if not isinstance(data, dict):
        return [ValidationIssue("", "must be a JSON object")]

    issues: list[ValidationIssue] = []
    issues.extend(_reject_unknown(data, _TOP_LEVEL_FIELDS, ""))

    schema_issues, present = require_field(data, "schema_version")
    issues.extend(schema_issues)
    if present:
        value = data["schema_version"]
        if isinstance(value, bool) or value != 1:
            issues.append(ValidationIssue("schema_version", "must equal 1"))

    id_issues, present = require_field(data, "device_id")
    issues.extend(id_issues)
    if present:
        issues.extend(check_pattern(data["device_id"], "device_id", DEVICE_ID_PATTERN))

    name_issues, present = require_field(data, "device_name")
    issues.extend(name_issues)
    if present:
        name = data["device_name"]
        issues.extend(check_string(name, "device_name", min_len=1, max_len=64))
        if isinstance(name, str) and not _control_free(name):
            issues.append(ValidationIssue("device_name", "must not contain controls"))

    issues.extend(_validate_os(data))
    issues.extend(_validate_hardware(data))

    ver_issues, present = require_field(data, "agent_version")
    issues.extend(ver_issues)
    if present:
        value = data["agent_version"]
        issues.extend(check_string(value, "agent_version", min_len=1, max_len=32))
        issues.extend(check_pattern(value, "agent_version", AGENT_VERSION_PATTERN))

    return issues


def _validate_os(data: dict[str, Any]) -> list[ValidationIssue]:
    issues, present = require_field(data, "os")
    issues_list = list(issues)
    if not present:
        return issues_list
    os_block = data["os"]
    if not isinstance(os_block, dict):
        return [ValidationIssue("os", "must be a JSON object")]
    issues_list.extend(_reject_unknown(os_block, _OS_FIELDS, "os."))
    for field_name in ("name", "version", "architecture"):
        field_issues, field_present = require_field(os_block, field_name)
        issues_list.extend(
            ValidationIssue(f"os.{i.field}", i.message) for i in field_issues
        )
        if field_present:
            issues_list.extend(
                check_string(
                    os_block[field_name], f"os.{field_name}", min_len=1, max_len=64
                )
            )
    return issues_list


def _validate_hardware(data: dict[str, Any]) -> list[ValidationIssue]:
    issues, present = require_field(data, "hardware")
    issues_list = list(issues)
    if not present:
        return issues_list
    hw = data["hardware"]
    if not isinstance(hw, dict):
        return [ValidationIssue("hardware", "must be a JSON object")]
    issues_list.extend(_reject_unknown(hw, _HARDWARE_FIELDS, "hardware."))

    cpu_model = hw.get("cpu_model")
    if cpu_model is not None:
        issues_list.extend(
            check_string(cpu_model, "hardware.cpu_model", min_len=1, max_len=128)
        )

    lc_issues, present = require_field(hw, "logical_cpus")
    issues_list.extend(
        ValidationIssue(f"hardware.{i.field}", i.message) for i in lc_issues
    )
    if present:
        issues_list.extend(
            check_int(hw["logical_cpus"], "hardware.logical_cpus", minimum=1,
                      maximum=1024)
        )

    physical = hw.get("physical_cores")
    if physical is not None:
        issues_list.extend(
            check_int(physical, "hardware.physical_cores", minimum=1, maximum=1024)
        )

    mem_issues, present = require_field(hw, "memory_total_bytes")
    issues_list.extend(
        ValidationIssue(f"hardware.{i.field}", i.message) for i in mem_issues
    )
    if present:
        issues_list.extend(
            check_int(
                hw["memory_total_bytes"],
                "hardware.memory_total_bytes",
                minimum=1,
                maximum=_MAX_MEMORY_BYTES,
            )
        )

    return issues_list
