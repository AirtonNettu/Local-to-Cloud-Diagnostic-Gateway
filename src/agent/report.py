"""Human-readable and JSON report rendering (design B.8, spec 31).

``render_text`` lays out three explicit sections (OBSERVED FACTS, RULE
EVALUATION, RECOMMENDATIONS) followed by OVERALL HEALTH and NETWORK STATUS.
Output is ASCII-safe for Windows consoles (no box-drawing characters).
``render_json`` emits ``DiagnosticResult.to_dict()`` for ``--json``.
"""

from __future__ import annotations

import json
from typing import Any

from shared.models.diagnostic import DiagnosticResult

__all__ = [
    "render_text",
    "render_json",
    "render_hardware_text",
    "format_bytes",
    "format_uptime",
]


def format_bytes(num: int | None) -> str:
    """Format a byte count as a human-readable string (ASCII units)."""
    if num is None:
        return "unavailable"
    value = float(num)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if value < 1024.0 or unit == "PiB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} PiB"


def format_uptime(seconds: int) -> str:
    """Format an uptime in seconds as ``2d 04h`` style."""
    days, rem = divmod(max(0, seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours:02d}h"
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m"


def _section(title: str) -> str:
    return f"{title}\n{'-' * len(title)}"


def render_json(result: DiagnosticResult) -> str:
    """Render a result as pretty JSON (``--json``)."""
    return json.dumps(result.to_dict(), indent=2, sort_keys=True)


def _facts_lines(facts: dict[str, Any]) -> list[str]:
    lines: list[str] = []

    system = facts.get("system")
    if isinstance(system, dict):
        lines.append(
            f"System: {system.get('os_name', 'unknown')} "
            f"{system.get('os_release', '')} ({system.get('architecture', '')})"
        )
        lines.append(f"Hostname: {system.get('hostname', 'unknown')}")
        uptime = system.get("uptime_seconds")
        if isinstance(uptime, int):
            lines.append(f"Uptime: {format_uptime(uptime)}")
    elif system is not None:
        lines.append(f"System: unavailable ({system})")

    cpu = facts.get("cpu")
    if isinstance(cpu, dict):
        cores = cpu.get("physical_cores")
        cores_text = f"{cores} cores / " if cores else ""
        lines.append(
            f"CPU: {cpu.get('model', 'unknown')} "
            f"({cores_text}{cpu.get('logical_cpus', '?')} logical), "
            f"{cpu.get('average_percent', '?')}% avg"
        )
    elif cpu is not None:
        lines.append(f"CPU: unavailable ({cpu})")

    memory = facts.get("memory")
    if isinstance(memory, dict):
        lines.append(
            f"Memory: {format_bytes(memory.get('used_bytes'))} / "
            f"{format_bytes(memory.get('total_bytes'))} "
            f"({memory.get('percent', '?')}%)"
        )
    elif memory is not None:
        lines.append(f"Memory: unavailable ({memory})")

    volumes = facts.get("storage")
    if isinstance(volumes, list):
        for vol in volumes:
            if not isinstance(vol, dict):
                continue
            lines.append(
                f"Volume {vol.get('mountpoint', '?')} "
                f"({vol.get('filesystem', '?')}): "
                f"{format_bytes(vol.get('used_bytes'))} / "
                f"{format_bytes(vol.get('total_bytes'))} "
                f"({vol.get('percent', '?')}%)"
            )
    elif volumes is not None:
        lines.append(f"Storage: unavailable ({volumes})")

    gpus = facts.get("gpus")
    if isinstance(gpus, list) and gpus:
        for gpu in gpus:
            if isinstance(gpu, dict):
                lines.append(
                    f"GPU: {gpu.get('name', 'unknown')} "
                    f"(driver {gpu.get('driver_version', 'unknown')})"
                )
    elif gpus is not None and not isinstance(gpus, list):
        lines.append(f"GPU: unavailable ({gpus})")

    network = facts.get("network")
    if isinstance(network, dict):
        gateways = network.get("gateways")
        if isinstance(gateways, list):
            lines.append(f"Gateways: {', '.join(gateways) or 'none'}")
        elif gateways is None:
            lines.append("Gateways: unavailable")
        dns = network.get("dns_servers")
        if isinstance(dns, list):
            lines.append(f"DNS servers: {', '.join(dns) or 'none'}")
        elif dns is None:
            lines.append("DNS servers: unavailable")

    diagnosis = facts.get("network_diagnosis")
    if isinstance(diagnosis, dict):
        evidence = diagnosis.get("evidence")
        if isinstance(evidence, list):
            for item in evidence:
                lines.append(f"  {item}")
    return lines


def render_text(result: DiagnosticResult) -> str:
    """Render the full three-section report (design B.8)."""
    parts: list[str] = []

    device = result.device_id or "not yet assigned"
    parts.append(f"Device: {device}")
    parts.append("")

    parts.append(_section("OBSERVED FACTS"))
    facts_lines = _facts_lines(result.facts)
    parts.extend(facts_lines if facts_lines else ["(no facts recorded)"])
    parts.append("")

    parts.append(_section("RULE EVALUATION"))
    for check in result.checks:
        parts.append(f"[{check.status.value}] {check.name}: {check.summary}")
        for item in check.evidence:
            parts.append(f"    - {item}")
    if result.alerts:
        parts.append("")
        parts.append("Alerts:")
        for alert in result.alerts:
            subject = f" ({alert.subject})" if alert.subject else ""
            parts.append(f"  [{alert.severity.value}]{subject} {alert.message}")
    parts.append("")

    parts.append(_section("RECOMMENDATIONS"))
    recommendations = _dedupe([a.recommendation for a in result.alerts])
    if recommendations:
        for rec in recommendations:
            parts.append(f"- {rec}")
    else:
        parts.append("No action needed.")
    parts.append("")

    parts.append(f"OVERALL HEALTH: {result.status.value}")
    parts.append(f"NETWORK STATUS: {result.network_status.value}")
    return "\n".join(parts)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def render_hardware_text(facts: dict[str, Any]) -> str:
    """Render the ``hardware`` command sections (CPU/memory/storage/system/GPU)."""
    parts: list[str] = [_section("HARDWARE")]
    lines = _facts_lines(facts)

    disks = facts.get("disks")
    if isinstance(disks, list) and disks:
        for index, disk in enumerate(disks):
            if isinstance(disk, dict):
                lines.append(
                    f"Disk disk{index} "
                    f"({disk.get('media_type', '?')}, {disk.get('bus_type', '?')}): "
                    f"health {disk.get('health_status', '?')}, "
                    f"{format_bytes(disk.get('size_bytes'))}"
                )
    elif disks is not None and not isinstance(disks, list):
        lines.append(f"Disk health: unavailable ({disks})")

    parts.extend(lines if lines else ["(no hardware facts available)"])
    return "\n".join(parts)
