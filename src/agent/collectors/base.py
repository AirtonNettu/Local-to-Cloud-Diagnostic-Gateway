"""Collector result type and the single isolation boundary ``run_collector``.

Every collector runs inside ``run_collector`` so one failing collector never
aborts the run (design B.6, spec 26 "continue with other collectors").
Exceptions map to a ``CollectorStatus`` and are logged with structured context;
error strings carry only the error class and message, never paths beyond
mountpoints.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar

import psutil

from agent.platform_support.base import (
    PlatformQueryError,
    PlatformUnavailableError,
)

__all__ = [
    "CollectorStatus",
    "CollectorResult",
    "PartialCollection",
    "run_collector",
]

T = TypeVar("T")

_log = logging.getLogger("agent.collectors")


class CollectorStatus(str, Enum):
    """Outcome of a collector run."""

    OK = "OK"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class CollectorResult(Generic[T]):
    """The outcome of one collector: status, data (when any) and errors."""

    name: str
    status: CollectorStatus
    data: T | None
    errors: tuple[str, ...]
    duration_ms: int

    @property
    def ok(self) -> bool:
        return self.status is CollectorStatus.OK

    @property
    def failed(self) -> bool:
        return self.status is CollectorStatus.FAILED

    @property
    def has_data(self) -> bool:
        return self.status in (CollectorStatus.OK, CollectorStatus.PARTIAL)


class PartialCollection(Exception, Generic[T]):
    """Raised by a collector that produced usable but incomplete data.

    ``run_collector`` reports it as ``PARTIAL`` with the carried data and the
    per-item error messages.
    """

    def __init__(self, data: T, errors: list[str]) -> None:
        self.data = data
        self.item_errors = list(errors)
        super().__init__("; ".join(errors))


def _error_text(exc: BaseException) -> str:
    message = str(exc).strip()
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


def run_collector(name: str, fn: Callable[[], T]) -> CollectorResult[T]:
    """Run ``fn`` and map any failure to a ``CollectorResult`` (never raises)."""
    start = time.perf_counter()
    try:
        data = fn()
    except PartialCollection as exc:
        duration_ms = int((time.perf_counter() - start) * 1000)
        _log.warning(
            "collector partial",
            extra={
                "event": "collector_partial",
                "component": name,
                "error": exc.item_errors[0] if exc.item_errors else "",
            },
        )
        return CollectorResult(
            name=name,
            status=CollectorStatus.PARTIAL,
            data=exc.data,
            errors=tuple(exc.item_errors),
            duration_ms=duration_ms,
        )
    except PlatformUnavailableError as exc:
        duration_ms = int((time.perf_counter() - start) * 1000)
        _log.debug(
            "collector unavailable",
            extra={
                "event": "collector_unavailable",
                "component": name,
                "error": _error_text(exc),
            },
        )
        return CollectorResult(
            name=name,
            status=CollectorStatus.UNAVAILABLE,
            data=None,
            errors=(_error_text(exc),),
            duration_ms=duration_ms,
        )
    except (PlatformQueryError, OSError, psutil.Error) as exc:
        duration_ms = int((time.perf_counter() - start) * 1000)
        _log.warning(
            "collector failed",
            extra={
                "event": "collector_failed",
                "component": name,
                "error_type": type(exc).__name__,
                "error": _error_text(exc),
            },
        )
        return CollectorResult(
            name=name,
            status=CollectorStatus.FAILED,
            data=None,
            errors=(_error_text(exc),),
            duration_ms=duration_ms,
        )
    except Exception as exc:  # noqa: BLE001 - last-resort isolation boundary.
        duration_ms = int((time.perf_counter() - start) * 1000)
        _log.error(
            "collector crashed",
            exc_info=True,
            extra={
                "event": "collector_failed",
                "component": name,
                "error_type": type(exc).__name__,
            },
        )
        return CollectorResult(
            name=name,
            status=CollectorStatus.FAILED,
            data=None,
            errors=(_error_text(exc),),
            duration_ms=duration_ms,
        )

    duration_ms = int((time.perf_counter() - start) * 1000)
    return CollectorResult(
        name=name,
        status=CollectorStatus.OK,
        data=data,
        errors=(),
        duration_ms=duration_ms,
    )
