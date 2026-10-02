"""Diagnostic result model: enums and frozen dataclasses.

Enums are ``str``-valued so they serialize directly to JSON. Dataclasses are
frozen and provide ``to_dict``; ``DiagnosticResult`` also provides
``from_dict`` so a stored run can be re-rendered as a report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = [
    "HealthStatus",
    "NetworkStatus",
    "CheckStatus",
    "Severity",
    "RunSource",
    "Check",
    "Alert",
    "Metric",
    "DiagnosticResult",
]


class HealthStatus(str, Enum):
    """Overall health of a diagnostic run."""

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


class NetworkStatus(str, Enum):
    """Network classification (see design B.7)."""

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNSTABLE = "UNSTABLE"
    OFFLINE = "OFFLINE"
    UNKNOWN = "UNKNOWN"


class CheckStatus(str, Enum):
    """Outcome of a single diagnostic check."""

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"


class Severity(str, Enum):
    """Severity of an alert."""

    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class RunSource(str, Enum):
    """Source of a diagnostic run; serialized lowercase."""

    LIVE = "live"
    DEMO = "demo"


@dataclass(frozen=True)
class Check:
    """One diagnostic check: what was tested, when, and the outcome."""

    name: str
    status: CheckStatus
    summary: str
    evidence: tuple[str, ...]
    checked_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "summary": self.summary,
            "evidence": list(self.evidence),
            "checked_at": self.checked_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Check:
        return cls(
            name=data["name"],
            status=CheckStatus(data["status"]),
            summary=data["summary"],
            evidence=tuple(data.get("evidence", ())),
            checked_at=data["checked_at"],
        )


@dataclass(frozen=True)
class Alert:
    """A rule finding with a recommendation."""

    rule_id: str
    severity: Severity
    message: str
    subject: str | None
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity.value,
            "message": self.message,
            "subject": self.subject,
            "recommendation": self.recommendation,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Alert:
        return cls(
            rule_id=data["rule_id"],
            severity=Severity(data["severity"]),
            message=data["message"],
            subject=data.get("subject"),
            recommendation=data["recommendation"],
        )


@dataclass(frozen=True)
class Metric:
    """A named numeric measurement with a unit and optional labels."""

    name: str
    value: float
    unit: str
    labels: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "labels": dict(self.labels),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Metric:
        return cls(
            name=data["name"],
            value=float(data["value"]),
            unit=data["unit"],
            labels=dict(data.get("labels", {})),
        )


@dataclass(frozen=True)
class DiagnosticResult:
    """The complete outcome of one diagnostic run.

    ``facts`` holds the rich local observation (collector outputs) used for the
    report; it is never uploaded wholesale. ``device_id`` is ``None`` only for a
    non-persisted ``health`` run on a data directory without an identity yet.
    """

    run_id: str
    device_id: str | None
    started_at: str
    finished_at: str
    source: RunSource
    status: HealthStatus
    network_status: NetworkStatus
    checks: tuple[Check, ...]
    alerts: tuple[Alert, ...]
    metrics: tuple[Metric, ...]
    facts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "device_id": self.device_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "source": self.source.value,
            "status": self.status.value,
            "network_status": self.network_status.value,
            "checks": [c.to_dict() for c in self.checks],
            "alerts": [a.to_dict() for a in self.alerts],
            "metrics": [m.to_dict() for m in self.metrics],
            "facts": self.facts,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DiagnosticResult:
        return cls(
            run_id=data["run_id"],
            device_id=data.get("device_id"),
            started_at=data["started_at"],
            finished_at=data["finished_at"],
            source=RunSource(data["source"]),
            status=HealthStatus(data["status"]),
            network_status=NetworkStatus(data["network_status"]),
            checks=tuple(Check.from_dict(c) for c in data.get("checks", ())),
            alerts=tuple(Alert.from_dict(a) for a in data.get("alerts", ())),
            metrics=tuple(Metric.from_dict(m) for m in data.get("metrics", ())),
            facts=dict(data.get("facts", {})),
        )
