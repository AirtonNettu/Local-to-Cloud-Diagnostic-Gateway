"""Health evaluator: run the rules and derive the overall status (design B.7)."""

from __future__ import annotations

from dataclasses import dataclass

from agent.collectors.base import CollectorStatus
from agent.config.settings import Thresholds
from agent.diagnostics.rules import RULES, DiagnosticInput, Rule
from shared.models.diagnostic import (
    Alert,
    Check,
    HealthStatus,
    Severity,
)

__all__ = ["Evaluation", "HealthEvaluator"]


@dataclass(frozen=True)
class Evaluation:
    """Overall status plus the produced checks and alerts."""

    status: HealthStatus
    checks: tuple[Check, ...]
    alerts: tuple[Alert, ...]


class HealthEvaluator:
    """Runs rules in order and derives the overall health status."""

    def __init__(self, rules: tuple[Rule, ...] = RULES) -> None:
        self._rules = rules

    def evaluate(self, data: DiagnosticInput, thresholds: Thresholds) -> Evaluation:
        checks: list[Check] = []
        alerts: list[Alert] = []
        for rule in self._rules:
            outcome = rule(data, thresholds)
            checks.append(outcome.check)
            alerts.extend(outcome.alerts)

        names = [c.name for c in checks]
        assert len(names) == len(set(names)), (  # noqa: S101 - uniqueness invariant
            f"duplicate check names: {names}"
        )

        status = self._overall_status(data, alerts)
        return Evaluation(status=status, checks=tuple(checks), alerts=tuple(alerts))

    @staticmethod
    def _overall_status(data: DiagnosticInput, alerts: list[Alert]) -> HealthStatus:
        if any(a.severity is Severity.CRITICAL for a in alerts):
            return HealthStatus.CRITICAL
        if any(a.severity is Severity.WARNING for a in alerts):
            return HealthStatus.DEGRADED
        core_failed = (
            data.cpu.status is CollectorStatus.FAILED
            and data.memory.status is CollectorStatus.FAILED
            and data.storage.status is CollectorStatus.FAILED
        )
        if core_failed:
            return HealthStatus.UNKNOWN
        return HealthStatus.HEALTHY
