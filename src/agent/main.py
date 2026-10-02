"""CLI entry point: argparse wiring, global options and exit-code handling.

Exit codes (design B.13): 0 success; 1 unexpected/storage error; 2 usage or
configuration error; 3 sync incomplete. ``KeyboardInterrupt`` maps to 130.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable, Sequence

from agent import __version__, commands

__all__ = ["main", "build_parser"]

_PROG = "diagnostic-agent"

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_SYNC_INCOMPLETE = 3
EXIT_INTERRUPTED = 130

_log = logging.getLogger("agent.main")


def build_parser() -> argparse.ArgumentParser:
    """Build the full argument parser with every subcommand."""
    parser = argparse.ArgumentParser(
        prog=_PROG,
        description=(
            "Local-to-Cloud Diagnostic Gateway: collect hardware, OS, storage "
            "and network diagnostics locally and optionally sync them to the "
            "cloud. Every local command works with no network connection."
        ),
    )
    parser.add_argument("--version", action="version", version=f"{_PROG} {__version__}")
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Override the configured file log level (and enable DEBUG on stderr).",
    )
    parser.add_argument(
        "--env-file",
        metavar="PATH",
        help="Path to a .env file to load (must exist).",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    scan = subparsers.add_parser(
        "scan",
        help="Run the full diagnostic pipeline and persist the result.",
        description="Run collectors, diagnostics and health rules, persist the "
        "run, and print a report.",
        epilog="Examples:\n  diagnostic-agent scan\n  diagnostic-agent scan --sync",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    scan.add_argument("--json", action="store_true", help="Emit the report as JSON.")
    scan.add_argument(
        "--sync", action="store_true", help="Run one sync cycle after scanning."
    )
    scan.set_defaults(func=commands.cmd_scan)

    hardware = subparsers.add_parser(
        "hardware",
        help="Show CPU, memory, storage, system, GPU and disk-health details.",
        description="Read-only hardware inventory. Never creates the database.",
    )
    hardware.add_argument("--json", action="store_true", help="Emit as JSON.")
    hardware.set_defaults(func=commands.cmd_hardware)

    network = subparsers.add_parser(
        "network",
        help="Show network collection and diagnostics with evidence and causes.",
        description="Read-only network diagnostics. Never creates the database.",
    )
    network.add_argument("--json", action="store_true", help="Emit as JSON.")
    network.set_defaults(func=commands.cmd_network)

    health = subparsers.add_parser(
        "health",
        help="Run the pipeline without persistence and print a compact summary.",
        description="Full pipeline without writing the database.",
    )
    health.add_argument("--json", action="store_true", help="Emit as JSON.")
    health.set_defaults(func=commands.cmd_health)

    sync = subparsers.add_parser(
        "sync",
        help="Run one bounded sync cycle against the configured cloud API.",
        description="Deliver pending queued events to the cloud backend.",
    )
    sync.add_argument(
        "--force", action="store_true", help="Ignore backoff and attempt now."
    )
    sync.set_defaults(func=commands.cmd_sync)

    status = subparsers.add_parser(
        "status",
        help="Show device identity, configuration summary and queue counts.",
        description="Read-only status overview. Secrets are never printed.",
    )
    status.set_defaults(func=commands.cmd_status)

    _add_queue_parser(subparsers)

    demo = subparsers.add_parser(
        "demo",
        help="Run deterministic demo scenarios over simulated inputs.",
        description="Exercise the real pipeline over simulated data.",
    )
    demo_group = demo.add_mutually_exclusive_group()
    demo_group.add_argument("--scenario", metavar="NAME", help="Run one scenario.")
    demo_group.add_argument("--all", action="store_true", help="Run all scenarios.")
    demo.add_argument("--json", action="store_true", help="Emit as JSON.")
    demo.set_defaults(func=commands.cmd_demo)

    run = subparsers.add_parser(
        "run",
        help="Loop scan + sync on the configured telemetry interval.",
        description="Scheduled loop; Ctrl+C exits within about one second.",
    )
    run.add_argument(
        "--iterations",
        type=int,
        metavar="N",
        help="Run a bounded number of iterations instead of looping forever.",
    )
    run.set_defaults(func=commands.cmd_run)

    return parser


def _add_queue_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    queue = subparsers.add_parser(
        "queue",
        help="Inspect and manage the local sync queue.",
        description="List queue entries, show stats, or requeue dead-lettered events.",
    )
    queue.set_defaults(func=commands.cmd_queue_stats)
    queue_sub = queue.add_subparsers(dest="queue_command", metavar="<queue-command>")

    q_list = queue_sub.add_parser("list", help="List queue entries.")
    q_list.add_argument("--state", metavar="S", help="Filter by state.")
    q_list.add_argument("--limit", type=int, metavar="N", help="Maximum rows to show.")
    q_list.set_defaults(func=commands.cmd_queue_list)

    q_stats = queue_sub.add_parser("stats", help="Show queue counts per state.")
    q_stats.set_defaults(func=commands.cmd_queue_stats)

    q_requeue = queue_sub.add_parser(
        "requeue", help="Move dead-lettered events back to PENDING."
    )
    requeue_group = q_requeue.add_mutually_exclusive_group(required=True)
    requeue_group.add_argument("--event-id", metavar="ID", help="Requeue one event.")
    requeue_group.add_argument(
        "--all-dead", action="store_true", help="Requeue every dead-lettered event."
    )
    q_requeue.set_defaults(func=commands.cmd_queue_requeue)


def main(argv: Sequence[str] | None = None) -> int:
    """Program entry point. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "command", None) is None:
        parser.print_help()
        return EXIT_USAGE

    func: Callable[[argparse.Namespace], int] | None = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return EXIT_USAGE

    try:
        return func(args)
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED
    except Exception:  # noqa: BLE001 - top-level guard; details go to the log.
        _log.error(
            "unexpected error",
            exc_info=True,
            extra={"event": "unexpected_error"},
        )
        print("An unexpected error occurred. See the log for details.", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
