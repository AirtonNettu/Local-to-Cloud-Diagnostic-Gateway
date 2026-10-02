"""CLI command handlers (thin orchestration).

Each handler returns a process exit code. The read-only commands wired here
(``hardware``, ``network``, ``health``) never create or migrate a database and
never import the sync package (local-first boundary, design B.18). The
remaining commands stay stubbed until their owning feature lands; a command
counts as implemented only when it actually performs its work.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from agent.config.settings import ConfigError, Settings, load_settings
from agent.diagnostics.engine import (
    Collected,
    collect_all,
    diagnose,
    evaluate_result,
)
from agent.diagnostics.facts import (
    build_facts,
    collector_fact,
    network_diagnosis_fact,
)
from agent.diagnostics.health import HealthEvaluator
from agent.diagnostics.network_diagnostics import NetworkDiagnosis
from agent.diagnostics.probes import SystemProber
from agent.identity import resolve_device_id
from agent.pipeline import DiagnosticPipeline, SystemClock, live_collector_set
from agent.platform_support import get_platform
from agent.report import render_hardware_text, render_json, render_text
from agent.storage import local_db
from agent.storage.local_db import LocalStore, StorageError
from shared.models.diagnostic import DiagnosticResult, RunSource

if TYPE_CHECKING:
    from agent.demo import DemoScenario, ScenarioResult
    from agent.sync.client import ApiClient
    from agent.sync.service import SyncReport

__all__ = [
    "cmd_scan",
    "cmd_hardware",
    "cmd_network",
    "cmd_health",
    "cmd_sync",
    "cmd_status",
    "cmd_queue_list",
    "cmd_queue_stats",
    "cmd_queue_requeue",
    "cmd_demo",
    "cmd_run",
]

_NOT_IMPLEMENTED_EXIT = 1
_EXIT_OK = 0
_EXIT_ERROR = 1
_EXIT_USAGE = 2
_EXIT_SYNC_INCOMPLETE = 3
_EXIT_INTERRUPTED = 130

_log = logging.getLogger("agent.commands")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _not_implemented(name: str) -> int:
    print(f"'{name}' is not available in this build yet (foundation only).")
    return _NOT_IMPLEMENTED_EXIT


def _load(args: argparse.Namespace) -> Settings | None:
    """Load settings, printing config errors to stderr. Returns None on failure."""
    env_file = getattr(args, "env_file", None)
    try:
        return load_settings(env_file=Path(env_file) if env_file else None)
    except ConfigError as exc:
        for error in exc.errors:
            print(f"Error: {error}", file=sys.stderr)
        return None


def cmd_scan(args: argparse.Namespace) -> int:
    """Run the full pipeline, persist the run, print the report (design B.8).

    A storage failure still prints the report (the run happened), logs
    ``event=storage_error`` and exits 1. ``--sync`` runs one sync cycle after a
    successful scan; the exit code follows the 1 > 3 > 0 precedence.
    """
    settings = _load(args)
    if settings is None:
        return _EXIT_USAGE

    platform_info = get_platform()
    pipeline = DiagnosticPipeline(
        settings=settings,
        collectors=live_collector_set(platform_info, settings),
        prober=SystemProber(),
        evaluator=HealthEvaluator(),
        clock=SystemClock(),
    )

    conn = None
    exit_code = _EXIT_OK
    sync_requested = getattr(args, "sync", False)
    try:
        conn = local_db.connect(settings.database_path)
        device_id = resolve_device_id(conn, settings, create=True)
        store = LocalStore(conn)
        result = pipeline.run(
            device_id, store, RunSource.LIVE, enqueue=settings.sync_enabled
        )
        if sync_requested and device_id is not None:
            sync_code = _run_sync_cycle(conn, settings, device_id, force=False)
            # Precedence: a storage error (1) outranks sync incomplete (3).
            if sync_code == _EXIT_SYNC_INCOMPLETE:
                exit_code = _EXIT_SYNC_INCOMPLETE
    except StorageError as exc:
        # The run itself may not have completed; produce one without a store so
        # the operator still sees current state, then signal the failure.
        result = pipeline.run(None, None, RunSource.LIVE, enqueue=False)
        _log.error(
            "local storage failed during scan",
            extra={
                "event": "storage_error",
                "error_class": type(exc.__cause__ or exc).__name__,
                "error_message": str(exc),
            },
        )
        exit_code = _EXIT_ERROR
    finally:
        if conn is not None:
            conn.close()

    if getattr(args, "json", False):
        print(render_json(result))
    else:
        print(render_text(result))

    return exit_code


def cmd_hardware(args: argparse.Namespace) -> int:
    """Read-only hardware inventory (never creates the database)."""
    settings = _load(args)
    if settings is None:
        return _EXIT_USAGE
    platform_info = get_platform()
    collected = collect_all(platform_info, settings)
    facts = build_facts(
        cpu=collected.cpu,
        memory=collected.memory,
        storage=collected.storage,
        system=collected.system,
        gpus=collected.gpus,
        disks=collected.disks,
        network=collected.network,
        diagnosis=None,
    )
    if getattr(args, "json", False):
        print(json.dumps(facts, indent=2, sort_keys=True))
    else:
        print(render_hardware_text(facts))
    return _EXIT_OK


def cmd_network(args: argparse.Namespace) -> int:
    """Read-only network collection + diagnostics (never creates the database)."""
    settings = _load(args)
    if settings is None:
        return _EXIT_USAGE
    platform_info = get_platform()
    collected = collect_all(platform_info, settings)
    diagnosis = diagnose(collected, SystemProber(), settings)

    if getattr(args, "json", False):
        payload = {
            "network": collector_fact(collected.network),
            "diagnosis": network_diagnosis_fact(diagnosis),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(_render_network_text(collected, diagnosis))
    return _EXIT_OK


def cmd_health(args: argparse.Namespace) -> int:
    """Full pipeline without persistence; compact summary (device may be None)."""
    settings = _load(args)
    if settings is None:
        return _EXIT_USAGE
    platform_info = get_platform()
    collected = collect_all(platform_info, settings)
    diagnosis = diagnose(collected, SystemProber(), settings)
    result = evaluate_result(
        device_id=settings.device_id or None,
        collected=collected,
        diagnosis=diagnosis,
        settings=settings,
        source=RunSource.LIVE,
        now=_utc_now,
    )
    if getattr(args, "json", False):
        print(render_json(result))
    else:
        print(_render_health_text(result))
    return _EXIT_OK


def _render_network_text(collected: Collected, diagnosis: NetworkDiagnosis) -> str:
    lines: list[str] = ["NETWORK", "-------"]
    net = collected.network
    if net.has_data and net.data is not None:
        info = net.data
        lines.append(f"Hostname: {info.hostname}")
        up = sum(1 for i in info.interfaces if i.is_up)
        lines.append(f"Interfaces: {len(info.interfaces)} total, {up} up")
        for iface in info.interfaces:
            state = "up" if iface.is_up else "down"
            addrs = ", ".join(list(iface.ipv4) + list(iface.ipv6)) or "no address"
            lines.append(f"  {iface.name} ({state}): {addrs}")
        if info.gateways is None:
            lines.append("Gateways: unavailable")
        else:
            lines.append(f"Gateways: {', '.join(info.gateways) or 'none'}")
        if info.dns_servers is None:
            lines.append("DNS servers: unavailable")
        else:
            lines.append(f"DNS servers: {', '.join(info.dns_servers) or 'none'}")
    else:
        lines.append("Network collection unavailable")

    lines.append("")
    lines.append("DIAGNOSIS")
    lines.append("---------")
    lines.append(f"Classification: {diagnosis.status.value}")
    if diagnosis.latency_avg_ms is not None:
        lines.append(f"Average latency: {diagnosis.latency_avg_ms:.1f} ms")
    if diagnosis.packet_loss_percent is not None:
        lines.append(f"Probe loss: {diagnosis.packet_loss_percent:.1f}%")
    lines.append("Evidence:")
    for item in diagnosis.evidence:
        lines.append(f"  - {item}")
    if diagnosis.possible_causes:
        lines.append("Possible causes:")
        for cause in diagnosis.possible_causes:
            lines.append(f"  - {cause}")
    return "\n".join(lines)


def _render_health_text(result: DiagnosticResult) -> str:
    lines: list[str] = []
    device = result.device_id or "not yet assigned"
    lines.append(f"Device: {device}")
    lines.append(f"OVERALL HEALTH: {result.status.value}")
    lines.append(f"NETWORK STATUS: {result.network_status.value}")
    lines.append("")
    if result.alerts:
        lines.append("Alerts:")
        for alert in result.alerts:
            subject = f" ({alert.subject})" if alert.subject else ""
            lines.append(f"  [{alert.severity.value}]{subject} {alert.message}")
        lines.append("")
        lines.append("Recommendations:")
        seen: set[str] = set()
        for alert in result.alerts:
            rec = alert.recommendation
            if rec and rec not in seen:
                seen.add(rec)
                lines.append(f"  - {rec}")
    else:
        lines.append("No alerts. No action needed.")
    return "\n".join(lines)


def build_api_client(settings: Settings) -> ApiClient:
    """Build the real ApiClient (patched in tests). Imported lazily (B.18)."""
    from agent.sync.client import ApiClient, UrllibTransport

    return ApiClient(
        base_url=settings.api_base_url,
        api_key=settings.api_key,
        transport=UrllibTransport(),
        timeout=settings.sync.http_timeout_s,
    )


def _run_sync_cycle(
    conn: sqlite3.Connection,
    settings: Settings,
    device_id: str,
    *,
    force: bool,
) -> int:
    """Run one sync cycle on an open connection; return 0 or 3."""
    from agent.sync.service import SyncService

    client = build_api_client(settings)
    service = SyncService(conn, settings, client, device_id=device_id)
    report = service.run_cycle(force=force)
    _print_sync_report(report)
    return _EXIT_SYNC_INCOMPLETE if report.had_failure else _EXIT_OK


def _print_sync_report(report: SyncReport) -> None:
    if report.disabled:
        print("Sync disabled: API_BASE_URL not configured")
        return
    print(
        "Sync: "
        f"accepted={report.accepted}, duplicates={report.duplicates}, "
        f"failed={report.failed}, dead_lettered={report.dead_lettered}"
    )
    if report.other_device_pending:
        print(f"Other-device pending: {report.other_device_pending}")
    if report.aborted:
        print(f"Cycle aborted: {report.aborted}")


def cmd_sync(args: argparse.Namespace) -> int:
    """Run one bounded sync cycle against the configured cloud API."""
    settings = _load(args)
    if settings is None:
        return _EXIT_USAGE
    if not settings.sync_enabled:
        print("Sync disabled: API_BASE_URL not configured")
        return _EXIT_OK

    force = getattr(args, "force", False)
    conn = None
    try:
        conn = local_db.connect(settings.database_path)
        device_id = resolve_device_id(conn, settings, create=True)
        if device_id is None:
            print("Sync: no device identity; run 'diagnostic-agent scan' first")
            return _EXIT_OK
        return _run_sync_cycle(conn, settings, device_id, force=force)
    except StorageError as exc:
        print(f"Error: local database unavailable: {exc}", file=sys.stderr)
        return _EXIT_ERROR
    finally:
        if conn is not None:
            conn.close()


def cmd_status(args: argparse.Namespace) -> int:
    """Read-only status: identity, config summary, last run, queue counts.

    Never creates or migrates the database. A missing DB file reports "no local
    data yet"; an unreadable DB (locked, corrupt, path is a directory) exits 1.
    """
    settings = _load(args)
    if settings is None:
        return _EXIT_USAGE

    lines: list[str] = ["STATUS", "------"]
    _append_config_summary(lines, settings)

    db_path = settings.database_path
    if not db_path.exists():
        lines.append("")
        lines.append("Local data: no local data yet")
        print("\n".join(lines))
        return _EXIT_OK

    conn = None
    try:
        conn = local_db.connect(db_path, read_only=True)
        device_id = resolve_device_id(conn, settings, create=False)
        _append_db_summary(lines, conn, settings, device_id)
    except local_db.SchemaOutdatedError:
        print(
            "local database needs migration; run 'diagnostic-agent scan'",
            file=sys.stderr,
        )
        return _EXIT_ERROR
    except StorageError as exc:
        print(f"Error: local database unavailable: {exc}", file=sys.stderr)
        return _EXIT_ERROR
    finally:
        if conn is not None:
            conn.close()

    print("\n".join(lines))
    return _EXIT_OK


def _append_config_summary(lines: list[str], settings: Settings) -> None:
    env_file = settings.env_file_loaded
    lines.append(f".env loaded: {env_file if env_file is not None else 'none'}")
    lines.append(f"Device name: {settings.device_name or '(hostname)'}")
    lines.append(f"Database path: {settings.database_path}")
    api_url = settings.api_base_url or "not set"
    lines.append(f"API base URL: {api_url}")
    lines.append(
        f"API key: {'configured' if settings.api_key else 'not set'}"
    )
    lines.append(
        f"Sync: {'enabled' if settings.sync_enabled else 'disabled'}"
    )


def _append_db_summary(
    lines: list[str],
    conn: sqlite3.Connection,
    settings: Settings,
    device_id: str | None,
) -> None:
    lines.append("")
    lines.append(f"Device ID: {device_id or 'not yet assigned'}")

    last_run = conn.execute(
        """
        SELECT started_at, status, network_status FROM diagnostic_runs
        ORDER BY started_at DESC LIMIT 1
        """
    ).fetchone()
    if last_run is None:
        lines.append("Last run: none")
    else:
        lines.append(
            f"Last run: {last_run[0]} "
            f"(health {last_run[1]}, network {last_run[2]})"
        )

    counts: dict[str, int] = {}
    for state, count in conn.execute(
        "SELECT state, COUNT(*) FROM sync_queue GROUP BY state"
    ).fetchall():
        counts[str(state)] = int(count)
    if counts:
        summary = ", ".join(
            f"{state}={count}" for state, count in sorted(counts.items())
        )
        lines.append(f"Queue: {summary}")
    else:
        lines.append("Queue: empty")

    last_attempt = conn.execute(
        """
        SELECT attempted_at, outcome FROM sync_attempts
        ORDER BY attempted_at DESC LIMIT 1
        """
    ).fetchone()
    if last_attempt is None:
        lines.append("Last sync attempt: none")
    else:
        lines.append(f"Last sync attempt: {last_attempt[0]} ({last_attempt[1]})")


def cmd_queue_list(args: argparse.Namespace) -> int:
    """List queue entries (read-only; never creates the database)."""
    settings = _load(args)
    if settings is None:
        return _EXIT_USAGE
    db_path = settings.database_path
    if not db_path.exists():
        print("Queue: no local data yet")
        return _EXIT_OK
    conn = None
    try:
        conn = local_db.connect(db_path, read_only=True)
        from agent.storage.queue import SyncQueue

        state = getattr(args, "state", None)
        limit = getattr(args, "limit", None) or 50
        rows = SyncQueue(conn).list(state, limit)
    except local_db.SchemaOutdatedError:
        print("local database needs migration; run 'diagnostic-agent scan'",
              file=sys.stderr)
        return _EXIT_ERROR
    except StorageError as exc:
        print(f"Error: local database unavailable: {exc}", file=sys.stderr)
        return _EXIT_ERROR
    finally:
        if conn is not None:
            conn.close()
    if not rows:
        print("Queue: empty")
        return _EXIT_OK
    for row in rows:
        print(
            f"{row['event_id']}  {row['state']}  "
            f"attempts={row['attempt_count']}  next={row['next_attempt_at']}"
        )
    return _EXIT_OK


def cmd_queue_stats(args: argparse.Namespace) -> int:
    """Show queue counts per state (read-only; never creates the database)."""
    settings = _load(args)
    if settings is None:
        return _EXIT_USAGE
    db_path = settings.database_path
    if not db_path.exists():
        print("Queue: no local data yet")
        return _EXIT_OK
    conn = None
    try:
        conn = local_db.connect(db_path, read_only=True)
        from agent.storage.queue import SyncQueue

        queue = SyncQueue(conn)
        counts = queue.stats()
        device_id = resolve_device_id(conn, settings, create=False)
        other = queue.other_device_pending(device_id) if device_id else 0
    except local_db.SchemaOutdatedError:
        print("local database needs migration; run 'diagnostic-agent scan'",
              file=sys.stderr)
        return _EXIT_ERROR
    except StorageError as exc:
        print(f"Error: local database unavailable: {exc}", file=sys.stderr)
        return _EXIT_ERROR
    finally:
        if conn is not None:
            conn.close()
    if counts:
        summary = ", ".join(
            f"{state}={count}" for state, count in sorted(counts.items())
        )
        print(f"Queue: {summary}")
    else:
        print("Queue: empty")
    if other:
        print(f"Other-device pending: {other}")
    return _EXIT_OK


def cmd_queue_requeue(args: argparse.Namespace) -> int:
    """Move dead-lettered events back to PENDING (writable)."""
    settings = _load(args)
    if settings is None:
        return _EXIT_USAGE
    conn = None
    try:
        conn = local_db.connect(settings.database_path)
        from agent.storage.queue import SyncQueue

        event_id = getattr(args, "event_id", None)
        requeued = SyncQueue(conn).requeue_dead(event_id, _utc_now())
    except StorageError as exc:
        print(f"Error: local database unavailable: {exc}", file=sys.stderr)
        return _EXIT_ERROR
    finally:
        if conn is not None:
            conn.close()
    print(f"Requeued {requeued} event(s).")
    return _EXIT_OK


def cmd_demo(args: argparse.Namespace) -> int:
    """Run deterministic demo scenarios over simulated inputs (design B.12).

    Default is ``--all``. ``--scenario NAME`` runs one scenario. Output is
    deterministic (except timestamps and IDs) and touches neither the real
    network, the live database, PowerShell nor psutil. Exits 2 on a usage or
    demo-database-guard error (see ``DemoRunner.prepare_database``).
    """
    settings = _load(args)
    if settings is None:
        return _EXIT_USAGE

    from agent.demo import (
        SCENARIOS,
        DemoRunner,
        scenario_names,
        scenario_summary,
    )

    scenario_name = getattr(args, "scenario", None)
    if scenario_name is not None:
        if scenario_name not in scenario_names():
            print(
                f"Error: unknown scenario '{scenario_name}'; choose from "
                f"{', '.join(scenario_names())}",
                file=sys.stderr,
            )
            return _EXIT_USAGE
        selected = [s for s in SCENARIOS if s.name == scenario_name]
    else:
        selected = list(SCENARIOS)

    runner = DemoRunner(settings)
    abort = runner.prepare_database()
    if abort is not None:
        return abort

    try:
        results = runner.run(selected)
    except StorageError as exc:
        print(f"Error: demo database unavailable: {exc}", file=sys.stderr)
        return _EXIT_ERROR

    offline_lines = _demo_offline_lines(settings, selected)
    if getattr(args, "json", False):
        payload = {
            "scenarios": [scenario_summary(r) for r in results],
            "offline_queue": offline_lines,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(_render_demo_text(results, offline_lines))
    return _EXIT_OK


def _demo_offline_lines(
    settings: Settings, selected: list[DemoScenario]
) -> list[str]:
    """Build the PENDING-with-one-OFFLINE-attempt lines for demo events.

    Only produced when OFFLINE_MODE ran (it performs the one sync cycle). Each
    enqueued demo event is PENDING with ``attempt_count = 0`` and one OFFLINE
    attempt row; the line names each scenario in run order.
    """
    from agent.demo import DEMO_DEVICE_ID

    if not any(s.name == "OFFLINE_MODE" for s in selected):
        return []
    conn = None
    try:
        conn = local_db.connect(settings.demo_database_path, read_only=True)
        rows = conn.execute(
            """
            SELECT r.scenario
            FROM sync_queue q
            JOIN diagnostic_runs r ON r.run_id = q.run_id
            WHERE q.device_id = ? AND q.state = 'PENDING'
            ORDER BY r.started_at ASC
            """,
            (DEMO_DEVICE_ID,),
        ).fetchall()
    except StorageError:
        return []
    finally:
        if conn is not None:
            conn.close()
    return [
        f"{row[0] or 'demo'}: PENDING, 1 offline attempt, "
        "will sync when connectivity returns"
        for row in rows
    ]


def _render_demo_text(
    results: list[ScenarioResult], offline_lines: list[str]
) -> str:
    lines: list[str] = ["DEMO", "----"]
    for item in results:
        scenario = item.scenario
        result = item.result
        lines.append("")
        lines.append(f"Scenario: {scenario.name}")
        lines.append(f"  {scenario.description}")
        lines.append(f"  Overall health: {result.status.value}")
        lines.append(f"  Network status: {result.network_status.value}")
        if result.alerts:
            alerts = ", ".join(a.rule_id for a in result.alerts)
            lines.append(f"  Alerts: {alerts}")
        else:
            lines.append("  Alerts: none")
    if offline_lines:
        lines.append("")
        lines.append("Offline queue:")
        for line in offline_lines:
            lines.append(f"  {line}")
    return "\n".join(lines)


def _sleep_interruptibly(
    seconds: float,
    *,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    """Sleep in slices of at most one second so Ctrl+C is responsive.

    ``sleep`` and ``monotonic`` are injected for deterministic tests. A
    ``KeyboardInterrupt`` propagates immediately (the caller maps it to 130).
    """
    if seconds <= 0:
        return
    deadline = monotonic() + seconds
    while True:
        remaining = deadline - monotonic()
        if remaining <= 0:
            return
        sleep(min(1.0, remaining))


def cmd_run(args: argparse.Namespace) -> int:
    """Loop scan + sync on the telemetry interval (design B.13).

    With ``--iterations N`` the loop runs N times and exits with the 1 > 3 > 0
    precedence over all iterations. Without it, the loop runs forever and ends
    only on Ctrl+C (130) or a startup configuration error (2).
    """
    settings = _load(args)
    if settings is None:
        return _EXIT_USAGE

    iterations = getattr(args, "iterations", None)
    sleep_fn: Callable[[float], None] = getattr(args, "_sleep", time.sleep)
    monotonic_fn: Callable[[], float] = getattr(args, "_monotonic", time.monotonic)

    worst = _EXIT_OK
    count = 0
    try:
        while iterations is None or count < iterations:
            code = _run_one_iteration(settings)
            worst = _worse_exit(worst, code)
            count += 1
            if iterations is not None and count >= iterations:
                break
            _sleep_interruptibly(
                float(settings.telemetry_interval_seconds),
                sleep=sleep_fn,
                monotonic=monotonic_fn,
            )
    except KeyboardInterrupt:
        return _EXIT_INTERRUPTED
    return worst


def _run_one_iteration(settings: Settings) -> int:
    """Run one scan + optional sync. Returns this iteration's exit code."""
    platform_info = get_platform()
    pipeline = DiagnosticPipeline(
        settings=settings,
        collectors=live_collector_set(platform_info, settings),
        prober=SystemProber(),
        evaluator=HealthEvaluator(),
        clock=SystemClock(),
    )
    conn = None
    try:
        conn = local_db.connect(settings.database_path)
        device_id = resolve_device_id(conn, settings, create=True)
        store = LocalStore(conn)
        pipeline.run(device_id, store, RunSource.LIVE, enqueue=settings.sync_enabled)
        if settings.sync_enabled and device_id is not None:
            return _run_sync_cycle(conn, settings, device_id, force=False)
        return _EXIT_OK
    except StorageError as exc:
        _log.error(
            "local storage failed during run iteration",
            extra={
                "event": "storage_error",
                "error_class": type(exc.__cause__ or exc).__name__,
                "error_message": str(exc),
            },
        )
        return _EXIT_ERROR
    finally:
        if conn is not None:
            conn.close()


def _worse_exit(current: int, candidate: int) -> int:
    """Apply the run exit precedence 1 > 3 > 0 (review NIT8)."""
    order = {_EXIT_ERROR: 2, _EXIT_SYNC_INCOMPLETE: 1, _EXIT_OK: 0}
    return current if order.get(current, 0) >= order.get(candidate, 0) else candidate
