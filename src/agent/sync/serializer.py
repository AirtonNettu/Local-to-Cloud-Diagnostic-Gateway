"""Telemetry/registration serializers with the privacy IP scrubber (M3).

``build_event`` is an explicit whitelist: only the fields in §B.9 are uploaded.
Evidence and messages are scrubbed of IP literals and truncated to the schema
limits, so interface names, DNS servers and gateway IPs never leave the host.
The model-string guarantee (no GPU/disk friendly names) is structural: the rules
never put them into checks/alerts, and a sentinel test asserts it.

``build_registration`` assembles the ``POST /v1/devices`` payload from facts with
the documented fallbacks for partial facts (§B.9).

The scrubber (review finding M3) replaces a token with ``<ip>`` only when
``ipaddress`` accepts it, so ``16:42:03``, ``C:\\`` and ``87.0%`` survive while
``fe80::1%12`` and ``2001:db8::53`` are redacted.
"""

from __future__ import annotations

import ipaddress
import platform
import re
from typing import Any

from agent import __version__
from shared.models.diagnostic import DiagnosticResult

__all__ = ["build_event", "build_registration", "scrub_ips"]

_IP_PLACEHOLDER = "<ip>"
# A loose candidate: any run of hex digits, dots, colons (and optional brackets
# or zone id). The ipaddress check below decides whether it is really an IP.
_IP_CANDIDATE = re.compile(r"\[?[0-9A-Fa-f:.]*[:.][0-9A-Fa-f:.%]*\]?")

# Schema limits mirrored from the contract (shared/schemas/telemetry.py).
_SUMMARY_MAX = 256
_EVIDENCE_ITEM_MAX = 256
_EVIDENCE_MAX_ITEMS = 10
_MESSAGE_MAX = 512
_SUBJECT_MAX = 64
_LABEL_VALUE_MAX = 64

# The model emits these units; the contract allows a smaller set, so map here.
_UNIT_MAP = {
    "milliseconds": "ms",
    "ms": "ms",
    "percent": "percent",
    "bytes": "bytes",
    "count": "count",
    "seconds": "seconds",
    "mhz": "mhz",
}


def scrub_ips(text: str) -> str:
    """Replace every IPv4/IPv6 literal with ``<ip>``; keep everything else.

    A candidate token is redacted only if ``ipaddress`` parses it, so timestamps
    (``16:42:03``), drive letters (``C:\\``) and percentages (``87.0%``) survive.
    """

    def repl(match: re.Match[str]) -> str:
        token = match.group(0).strip("[]").split("%", 1)[0]
        try:
            ipaddress.ip_address(token)
        except ValueError:
            return match.group(0)
        return _IP_PLACEHOLDER

    return _IP_CANDIDATE.sub(repl, text)


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit]


def _clean(text: str, limit: int) -> str:
    return _truncate(scrub_ips(text), limit)


def build_event(result: DiagnosticResult) -> dict[str, Any]:
    """Build the whitelisted, scrubbed telemetry event for one run (§B.9)."""
    event_id = result.facts.get("event_id") if isinstance(result.facts, dict) else None
    return {
        "event_id": event_id or _event_id_from_run(result),
        "event_type": "diagnostic_run",
        "schema_version": 1,
        "timestamp": result.finished_at,
        "source": result.source.value,
        "status": result.status.value,
        "network_status": result.network_status.value,
        "checks": [_build_check(c) for c in result.checks],
        "alerts": [_build_alert(a) for a in result.alerts],
        "metrics": [_build_metric(m) for m in result.metrics],
    }


def _event_id_from_run(result: DiagnosticResult) -> str:
    # The queue payload carries the real event_id; a direct caller (tests, the
    # sentinel) may build an event straight from a result. Fall back to run_id,
    # which is also a UUIDv7, so the event still validates.
    return result.run_id


def _build_check(check: Any) -> dict[str, Any]:
    evidence = [
        _clean(str(item), _EVIDENCE_ITEM_MAX)
        for item in list(check.evidence)[:_EVIDENCE_MAX_ITEMS]
    ]
    return {
        "name": check.name,
        "status": check.status.value,
        "summary": _clean(check.summary, _SUMMARY_MAX),
        "evidence": evidence,
    }


def _build_alert(alert: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "rule_id": alert.rule_id,
        "severity": alert.severity.value,
        "message": _clean(alert.message, _MESSAGE_MAX),
    }
    if alert.subject is not None:
        out["subject"] = _clean(str(alert.subject), _SUBJECT_MAX)
    return out


def _build_metric(metric: Any) -> dict[str, Any]:
    labels = {
        str(key): _clean(str(value), _LABEL_VALUE_MAX)
        for key, value in dict(metric.labels).items()
    }
    out: dict[str, Any] = {
        "name": metric.name,
        "value": metric.value,
        "unit": _UNIT_MAP.get(metric.unit, metric.unit),
    }
    if labels:
        out["labels"] = labels
    return out


def build_registration(
    device_id: str, device_name: str, facts: Any | None
) -> dict[str, Any]:
    """Build the ``POST /v1/devices`` payload with partial-facts fallbacks."""
    fact_map: dict[str, Any] = facts if isinstance(facts, dict) else {}
    cpu = _sub_dict(fact_map, "cpu")
    system = _sub_dict(fact_map, "system")
    memory = _sub_dict(fact_map, "memory")

    cpu_model = cpu.get("model")
    physical_cores = cpu.get("physical_cores")
    logical_cpus = cpu.get("logical_cpus")
    memory_total = memory.get("total_bytes")

    hardware: dict[str, Any] = {
        "cpu_model": cpu_model if isinstance(cpu_model, str) and cpu_model else None,
        "logical_cpus": _positive_int(logical_cpus, _default_logical_cpus()),
        "physical_cores": physical_cores if _is_positive_int(physical_cores) else None,
        "memory_total_bytes": _positive_int(memory_total, _default_memory_bytes()),
    }
    return {
        "schema_version": 1,
        "device_id": device_id,
        "device_name": device_name,
        "os": {
            "name": _string_or(system.get("os_name"), platform.system() or "unknown"),
            "version": _string_or(
                system.get("os_version"), platform.version() or "unknown"
            ),
            "architecture": _string_or(
                system.get("architecture"), platform.machine() or "unknown"
            ),
        },
        "hardware": hardware,
        "agent_version": __version__,
    }


def _sub_dict(fact_map: dict[str, Any], key: str) -> dict[str, Any]:
    value = fact_map.get(key)
    return value if isinstance(value, dict) else {}


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _positive_int(value: Any, fallback: int) -> int:
    return value if _is_positive_int(value) else fallback


def _string_or(value: Any, fallback: str) -> str:
    return value if isinstance(value, str) and value else fallback


def _default_logical_cpus() -> int:
    import os

    return os.cpu_count() or 1


def _default_memory_bytes() -> int:
    try:
        import psutil

        return int(psutil.virtual_memory().total)
    except Exception:  # noqa: BLE001 - psutil failure falls back to a safe value.
        return 1
