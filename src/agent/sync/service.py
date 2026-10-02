"""Sync cycle orchestration (design B.9).

``SyncService.run_cycle`` recovers stale leases, ensures the device is
registered (with a fingerprint so an unchanged profile is not re-sent), then
claims due events and delivers them in greedy, byte-packed batches. Every
network outcome flows through the ordered client classification; the queue state
machine owns the resulting transitions. Being offline or misconfigured never
consumes the retry budget: only enveloped 4xx, a single-event 413, a per-item
rejection other than CLOCK_SKEW, or a local validation failure dead-letters.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import sqlite3
from dataclasses import dataclass
from typing import Any, Literal

from agent.config.settings import Settings
from agent.storage.queue import QueuedEvent, SyncQueue
from agent.sync.client import (
    ApiClient,
    AuthError,
    ConfigurationError,
    DeviceNotRegisteredError,
    ItemResult,
    MalformedResponseError,
    OfflineError,
    PayloadTooLargeError,
    PermanentSyncError,
    TransientSyncError,
)
from agent.sync.retry import BackoffPolicy
from agent.sync.serializer import build_registration
from shared.models.diagnostic import DiagnosticResult
from shared.schemas.common import MAX_REQUEST_BYTES
from shared.schemas.device import validate_device_registration
from shared.utils.timeutil import to_iso, utc_now

__all__ = ["SyncReport", "SyncService"]

_log = logging.getLogger("agent.sync")

AbortReason = Literal["offline", "auth", "config", "registration"]


@dataclass
class SyncReport:
    """Outcome of one cycle: counts per terminal effect and why it ended."""

    accepted: int = 0
    duplicates: int = 0
    dead_lettered: int = 0
    failed: int = 0
    aborted: AbortReason | None = None
    disabled: bool = False
    other_device_pending: int = 0
    registered: bool = False

    @property
    def had_failure(self) -> bool:
        """True when the CLI should exit 3 (incomplete sync)."""
        return (
            self.aborted is not None
            or self.dead_lettered > 0
            or self.failed > 0
        )


class SyncService:
    """Runs one bounded sync cycle against the configured cloud API."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        settings: Settings,
        client: ApiClient,
        *,
        device_id: str,
        rng: random.Random | None = None,
        now: Any = utc_now,
    ) -> None:
        self._conn = conn
        self._settings = settings
        self._client = client
        self._device_id = device_id
        self._queue = SyncQueue(conn)
        self._now = now
        policy_rng = rng or random.Random()  # noqa: S311 - jitter, not crypto
        self._policy = BackoffPolicy(
            base_s=settings.sync.backoff_base_s,
            max_s=settings.sync.backoff_max_s,
            rng=policy_rng,
        )
        self._retry_limit = settings.sync.retry_limit
        self._batch_size = settings.sync.batch_size
        self._max_batches = settings.sync.max_batches
        self._handled: set[str] = set()

    def run_cycle(self, force: bool = False) -> SyncReport:
        """Execute one sync cycle. Returns a ``SyncReport``."""
        from agent.config.settings import SyncSettings  # noqa: F401 (B.9 reference)

        if not self._settings.sync_enabled or not self._settings.api_key:
            return SyncReport(disabled=True)

        report = SyncReport()
        report.other_device_pending = self._queue.other_device_pending(
            self._device_id
        )

        self._queue.recover_stale(self._device_id, self._now())
        if self._queue.count_due(self._device_id, self._now(), force=force) == 0:
            return report

        if not self._ensure_registration(report):
            return report

        self._handled = set()
        for _ in range(self._max_batches):
            batch = self._queue.claim_due(
                self._device_id,
                self._batch_size,
                self._now(),
                force=force,
                exclude=frozenset(self._handled),
            )
            if not batch:
                break
            keep_going = self._process_batch(batch, report, force=force)
            if not keep_going:
                break
        return report

    # -- registration -----------------------------------------------------
    def _ensure_registration(self, report: SyncReport) -> bool:
        """Register when the fingerprint changed. Returns False to abort."""
        payload = self._registration_payload()
        if payload is None:
            # No run on record for this device, or psutil failed: skip and let
            # telemetry proceed (a 409 is handled by the normal path).
            return True
        fingerprint = _fingerprint(payload)
        if fingerprint == self._stored_fingerprint():
            return True
        try:
            self._client.register_device(payload)
        except Exception as exc:  # noqa: BLE001 - routed through the handler
            return self._handle_registration_failure(exc, report)
        self._store_fingerprint(fingerprint)
        report.registered = True
        return True

    def _handle_registration_failure(
        self, exc: Exception, report: SyncReport
    ) -> bool:
        """Apply the registration failure branches (B.9 step 2). False=abort."""
        if isinstance(exc, OfflineError):
            self._offline_release(report, error_code="REGISTRATION_OFFLINE")
            report.aborted = "offline"
            _log.warning("sync offline during registration",
                         extra={"event": "sync_offline"})
            return False
        if isinstance(exc, (TransientSyncError, MalformedResponseError)):
            self._registration_transient(exc, report)
            report.aborted = "registration"
            return False
        if isinstance(exc, AuthError):
            report.aborted = "auth"
            _log.error("auth failure during registration",
                       extra={"event": "sync_auth_error"})
            return False
        if isinstance(exc, ConfigurationError):
            report.aborted = "config"
            _log.error("config error during registration",
                       extra={"event": "sync_config_error"})
            return False
        if isinstance(exc, PermanentSyncError):
            # Enveloped 4xx on registration: a local bug (payload passed the
            # shared validator). Abort without touching events.
            report.aborted = "registration"
            _log.error("registration rejected by server",
                       extra={"event": "registration_rejected"})
            return False
        raise exc

    def _registration_transient(
        self, exc: Exception, report: SyncReport
    ) -> None:
        http_status = getattr(exc, "http_status", None)
        batch = self._queue.claim_due(
            self._device_id, self._batch_size, self._now()
        )
        for event in batch:
            self._fail(
                event,
                report,
                error="registration failed",
                error_code="REGISTRATION_FAILED",
                outcome="TRANSIENT_ERROR",
                http_status=http_status,
            )

    def _offline_release(self, report: SyncReport, *, error_code: str) -> None:
        batch = self._queue.claim_due(
            self._device_id, self._batch_size, self._now()
        )
        self._queue.release(
            [e.event_id for e in batch],
            self._now(),
            outcome="OFFLINE",
            error_code=error_code,
            error_message="connectivity error",
        )

    # -- batches ----------------------------------------------------------
    def _process_batch(
        self, batch: list[QueuedEvent], report: SyncReport, *, force: bool
    ) -> bool:
        packed, overflow = self._pack(batch)
        if overflow:
            self._queue.release([e.event_id for e in overflow], self._now())
        if not packed:
            return False
        return self._deliver(packed, report, allow_reregister=True)

    def _deliver(
        self,
        packed: list[QueuedEvent],
        report: SyncReport,
        *,
        allow_reregister: bool,
    ) -> bool:
        self._handled.update(e.event_id for e in packed)
        events = [self._event_payload(e) for e in packed]
        try:
            result = self._client.send_telemetry(self._device_id, events)
        except OfflineError:
            self._queue.release(
                [e.event_id for e in packed],
                self._now(),
                outcome="OFFLINE",
                error_code="CONNECTIVITY",
                error_message="connectivity error",
            )
            report.aborted = "offline"
            _log.warning("sync offline", extra={"event": "sync_offline"})
            return False
        except AuthError:
            self._queue.release(
                [e.event_id for e in packed], self._now(),
                outcome="AUTH_ERROR", error_code="AUTH_ERROR",
            )
            report.aborted = "auth"
            return False
        except ConfigurationError:
            self._queue.release(
                [e.event_id for e in packed], self._now(),
                outcome="CONFIG_ERROR", error_code="CONFIG_ERROR",
            )
            report.aborted = "config"
            return False
        except PayloadTooLargeError:
            return self._split_413(packed, report)
        except PermanentSyncError as exc:
            for event in packed:
                self._dead(event, report, error=str(exc), error_code=exc.code)
            return True
        except DeviceNotRegisteredError:
            return self._handle_409(packed, report, allow_reregister=allow_reregister)
        except (MalformedResponseError, TransientSyncError) as exc:
            http_status = getattr(exc, "http_status", None)
            for event in packed:
                self._fail(
                    event, report, error=str(exc),
                    error_code="TRANSIENT", http_status=http_status,
                )
            return True
        self._apply_items(packed, result.results, report)
        _log.info(
            "sync batch sent",
            extra={
                "event": "sync_batch_sent",
                "count": len(packed),
                "request_id": result.request_id,
            },
        )
        return True

    def _split_413(self, packed: list[QueuedEvent], report: SyncReport) -> bool:
        """Multi-event 413: release the batch, resend one event per request."""
        self._queue.release([e.event_id for e in packed], self._now())
        for event in packed:
            reclaimed = self._queue.claim_due(
                self._device_id, 1, self._now(), force=True
            )
            target = next(
                (e for e in reclaimed if e.event_id == event.event_id), None
            )
            if target is None:
                self._queue.release([e.event_id for e in reclaimed], self._now())
                continue
            self._deliver([target], report, allow_reregister=False)
        return True

    def _handle_409(
        self, packed: list[QueuedEvent], report: SyncReport, *, allow_reregister: bool
    ) -> bool:
        if not allow_reregister:
            for event in packed:
                self._fail(
                    event, report, error="device not registered",
                    error_code="DEVICE_NOT_REGISTERED",
                )
            return True
        payload = self._registration_payload()
        if payload is None:
            for event in packed:
                self._fail(
                    event, report, error="cannot build registration",
                    error_code="REGISTRATION_FAILED",
                )
            return True
        try:
            self._client.register_device(payload)
        except Exception as exc:  # noqa: BLE001 - route the already-claimed batch
            return self._reregister_failure(exc, packed, report)
        self._store_fingerprint(_fingerprint(payload))
        report.registered = True
        return self._deliver(packed, report, allow_reregister=False)

    def _reregister_failure(
        self, exc: Exception, packed: list[QueuedEvent], report: SyncReport
    ) -> bool:
        if isinstance(exc, OfflineError):
            self._queue.release(
                [e.event_id for e in packed], self._now(),
                outcome="OFFLINE", error_code="REGISTRATION_OFFLINE",
                error_message="connectivity error",
            )
            report.aborted = "offline"
            return False
        if isinstance(exc, (TransientSyncError, MalformedResponseError)):
            http_status = getattr(exc, "http_status", None)
            for event in packed:
                self._fail(
                    event, report, error="registration failed",
                    error_code="REGISTRATION_FAILED", outcome="TRANSIENT_ERROR",
                    http_status=http_status,
                )
            report.aborted = "registration"
            return False
        if isinstance(exc, AuthError):
            self._queue.release(
                [e.event_id for e in packed], self._now(),
                outcome="AUTH_ERROR", error_code="AUTH_ERROR",
            )
            report.aborted = "auth"
            return False
        if isinstance(exc, ConfigurationError):
            self._queue.release(
                [e.event_id for e in packed], self._now(),
                outcome="CONFIG_ERROR", error_code="CONFIG_ERROR",
            )
            report.aborted = "config"
            return False
        if isinstance(exc, PermanentSyncError):
            self._queue.release([e.event_id for e in packed], self._now())
            report.aborted = "registration"
            _log.error(
                "registration rejected", extra={"event": "registration_rejected"}
            )
            return False
        raise exc

    # -- per-item results -------------------------------------------------
    def _apply_items(
        self,
        packed: list[QueuedEvent],
        results: list[ItemResult],
        report: SyncReport,
    ) -> None:
        by_id = {e.event_id: e for e in packed}
        for item in results:
            event = by_id.get(item.event_id)
            if event is None:
                continue
            if item.status in ("accepted", "duplicate"):
                self._queue.mark_synced(
                    [event.event_id],
                    outcome="ACCEPTED" if item.status == "accepted" else "DUPLICATE",
                    attempt=event.attempt_count + 1,
                    now=self._now(),
                )
                if item.status == "accepted":
                    report.accepted += 1
                else:
                    report.duplicates += 1
            elif item.code == "CLOCK_SKEW":
                _log.warning(
                    "clock skew", extra={"event": "clock_skew"}
                )
                self._fail(
                    event, report, error="local clock ahead of server",
                    error_code="CLOCK_SKEW",
                )
            else:
                self._dead(
                    event, report, error=item.message or "rejected",
                    error_code=item.code,
                )

    # -- transition helpers ----------------------------------------------
    def _fail(
        self,
        event: QueuedEvent,
        report: SyncReport,
        *,
        error: str,
        error_code: str | None,
        outcome: str = "TRANSIENT_ERROR",
        http_status: int | None = None,
    ) -> None:
        attempt = event.attempt_count + 1
        state = self._queue.mark_failed(
            event.event_id,
            error,
            attempt,
            self._policy,
            self._now(),
            retry_limit=self._retry_limit,
            outcome=outcome,
            error_code=error_code,
            http_status=http_status,
        )
        if state == "DEAD_LETTER":
            report.dead_lettered += 1
        else:
            report.failed += 1

    def _dead(
        self,
        event: QueuedEvent,
        report: SyncReport,
        *,
        error: str,
        error_code: str | None,
    ) -> None:
        self._queue.mark_dead(
            event.event_id,
            error,
            event.attempt_count + 1,
            self._now(),
            outcome="REJECTED",
            error_code=error_code,
        )
        report.dead_lettered += 1

    # -- packing ----------------------------------------------------------
    def _pack(
        self, batch: list[QueuedEvent]
    ) -> tuple[list[QueuedEvent], list[QueuedEvent]]:
        packed: list[QueuedEvent] = []
        overflow: list[QueuedEvent] = []
        for event in batch:
            candidate = packed + [event]
            envelope = {
                "schema_version": 1,
                "device_id": self._device_id,
                "events": [self._event_payload(e) for e in candidate],
            }
            size = len(json.dumps(envelope, separators=(",", ":")).encode("utf-8"))
            too_big = size > MAX_REQUEST_BYTES or len(candidate) > self._batch_size
            if packed and too_big:
                overflow.append(event)
            else:
                packed.append(event)
        return packed, overflow

    def _event_payload(self, event: QueuedEvent) -> dict[str, Any]:
        from agent.sync.serializer import build_event

        payload = json.loads(event.payload_json)
        result = DiagnosticResult.from_dict(payload["result"])
        built = build_event(result)
        built["event_id"] = payload["event_id"]
        return built

    # -- registration payload + fingerprint ------------------------------
    def _registration_payload(self) -> dict[str, Any] | None:
        row = self._conn.execute(
            """
            SELECT result_json FROM diagnostic_runs
            WHERE device_id = ? ORDER BY started_at DESC LIMIT 1
            """,
            (self._device_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            result = DiagnosticResult.from_dict(json.loads(row[0]))
        except (ValueError, KeyError):
            return None
        device_name = self._settings.device_name
        if not device_name and isinstance(result.facts, dict):
            system = result.facts.get("system")
            if isinstance(system, dict):
                device_name = str(system.get("hostname") or "")
        payload = build_registration(
            self._device_id, device_name or self._device_id, result.facts
        )
        if validate_device_registration(payload):
            _log.warning(
                "registration payload failed local validation",
                extra={"event": "registration_local_invalid"},
            )
            return None
        return payload

    def _stored_fingerprint(self) -> str | None:
        row = self._conn.execute(
            "SELECT registration_fingerprint FROM devices WHERE device_id = ?",
            (self._device_id,),
        ).fetchone()
        return str(row[0]) if row is not None and row[0] is not None else None

    def _store_fingerprint(self, fingerprint: str) -> None:
        self._conn.execute(
            """
            UPDATE devices SET registration_fingerprint = ?, registered_at = ?
            WHERE device_id = ?
            """,
            (fingerprint, to_iso(self._now()), self._device_id),
        )
        self._conn.commit()


def _fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
