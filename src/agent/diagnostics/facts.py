"""Build the ``facts`` dict from collector results and the network diagnosis.

``facts`` is the rich local observation used only for the report; it is never
uploaded wholesale (design B.3). Each collector contributes either its data (as
a plain dict/list) or a short "unavailable (<reason>)" string so the report can
show what was missing.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from agent.collectors.base import CollectorResult
from agent.diagnostics.network_diagnostics import NetworkDiagnosis

__all__ = ["collector_fact", "network_diagnosis_fact", "build_facts"]


def _unavailable_reason(result: CollectorResult[Any]) -> str:
    if result.errors:
        return result.errors[0]
    return result.status.value.lower()


def collector_fact(result: CollectorResult[Any]) -> Any:
    """Return a serializable fact for one collector result."""
    if result.has_data and result.data is not None:
        data = result.data
        if isinstance(data, list):
            return [asdict(item) if _is_dataclass(item) else item for item in data]
        if _is_dataclass(data):
            return asdict(data)
        return data
    return f"unavailable ({_unavailable_reason(result)})"


def _is_dataclass(obj: Any) -> bool:
    return hasattr(type(obj), "__dataclass_fields__")


def network_diagnosis_fact(diagnosis: NetworkDiagnosis) -> dict[str, Any]:
    """Return a serializable fact for the network diagnosis (evidence/causes)."""
    return {
        "status": diagnosis.status.value,
        "local_network_available": diagnosis.local_network_available,
        "gateway_reachable": diagnosis.gateway_reachable,
        "internet_available": diagnosis.internet_available,
        "latency_avg_ms": diagnosis.latency_avg_ms,
        "packet_loss_percent": diagnosis.packet_loss_percent,
        "dns_state": diagnosis.dns_state,
        "evidence": list(diagnosis.evidence),
        "possible_causes": list(diagnosis.possible_causes),
    }


def build_facts(
    *,
    cpu: CollectorResult[Any],
    memory: CollectorResult[Any],
    storage: CollectorResult[Any],
    system: CollectorResult[Any],
    gpus: CollectorResult[Any],
    disks: CollectorResult[Any],
    network: CollectorResult[Any],
    diagnosis: NetworkDiagnosis | None,
) -> dict[str, Any]:
    """Assemble the ``facts`` dict for a report."""
    facts: dict[str, Any] = {
        "cpu": collector_fact(cpu),
        "memory": collector_fact(memory),
        "storage": collector_fact(storage),
        "system": collector_fact(system),
        "gpus": collector_fact(gpus),
        "disks": collector_fact(disks),
        "network": collector_fact(network),
    }
    if diagnosis is not None:
        facts["network_diagnosis"] = network_diagnosis_fact(diagnosis)
    return facts
