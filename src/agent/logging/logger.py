"""Agent logging setup: JSON file handler plus a short stderr text handler.

If the log file cannot be opened the agent keeps running with stderr only and
prints a single warning: logging failures must never break diagnostics.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from agent.config.settings import Settings
from shared.utils.json_logging import JsonFormatter, RedactionFilter

__all__ = ["configure_logging"]

_LOG_MAX_BYTES = 1_000_000
_LOG_BACKUP_COUNT = 3


def configure_logging(settings: Settings, *, console_debug: bool = False) -> None:
    """Configure the root logger with a JSON file handler and a stderr handler.

    ``console_debug`` lowers the stderr handler to DEBUG (used by
    ``--log-level DEBUG``); otherwise it stays at WARNING so normal command
    output on stdout is not drowned out.
    """
    root = logging.getLogger()
    # Reset any handlers from a previous configuration (e.g. in tests).
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.setLevel(logging.DEBUG)

    redaction = RedactionFilter()

    file_level = getattr(logging, settings.log_level, logging.INFO)
    file_handler = _build_file_handler(settings.log_file)
    if file_handler is not None:
        file_handler.setLevel(file_level)
        file_handler.setFormatter(JsonFormatter())
        file_handler.addFilter(redaction)
        root.addHandler(file_handler)

    console = logging.StreamHandler(stream=sys.stderr)
    console.setLevel(logging.DEBUG if console_debug else logging.WARNING)
    console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    console.addFilter(redaction)
    root.addHandler(console)

    if file_handler is None:
        root.warning(
            "could not open log file; continuing with stderr logging only",
            extra={"event": "log_file_unavailable"},
        )


def _build_file_handler(log_file: Path) -> RotatingFileHandler | None:
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        return RotatingFileHandler(
            log_file,
            maxBytes=_LOG_MAX_BYTES,
            backupCount=_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError:
        return None
