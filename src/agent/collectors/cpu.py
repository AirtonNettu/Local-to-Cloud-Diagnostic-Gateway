"""CPU collector (design B.6).

Samples CPU utilization with a blocking interval (the first non-blocking psutil
reading is meaningless). The model name comes from the platform module first
(the Win32_Processor marketing name); on failure it falls back to
``platform.processor()`` and then ``"unknown"``. A fallback is recorded in
``errors`` for visibility but does not make the collector PARTIAL.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass

import psutil

from agent.platform_support.base import (
    PlatformInfo,
    PlatformQueryError,
    PlatformUnavailableError,
)

__all__ = ["CpuInfo", "collect_cpu"]


@dataclass(frozen=True)
class CpuInfo:
    """CPU identity, counts, utilization samples and frequency.

    ``notes`` records non-fatal fallbacks (e.g. the CPU name came from
    ``platform.processor()``); it never changes the collector status.
    """

    model: str
    logical_cpus: int
    physical_cores: int | None
    current_percent: float
    average_percent: float
    samples: tuple[float, ...]
    frequency_current_mhz: float | None
    frequency_max_mhz: float | None
    notes: tuple[str, ...] = ()


def _resolve_model(platform_info: PlatformInfo, errors: list[str]) -> str:
    try:
        name = platform_info.cpu_name()
        if name.strip():
            return name.strip()
    except (PlatformUnavailableError, PlatformQueryError) as exc:
        errors.append(f"cpu name fallback: {type(exc).__name__}")
    fallback = platform.processor()
    if fallback.strip():
        return fallback.strip()
    return "unknown"


def collect_cpu(
    platform_info: PlatformInfo,
    *,
    sample_count: int,
    sample_interval_seconds: float,
) -> CpuInfo:
    """Collect CPU information. Returns PARTIAL only on a non-fatal frequency gap."""
    errors: list[str] = []
    model = _resolve_model(platform_info, errors)

    samples: list[float] = []
    for _ in range(max(1, sample_count)):
        samples.append(float(psutil.cpu_percent(interval=sample_interval_seconds)))
    current = samples[-1]
    average = sum(samples) / len(samples)

    logical = psutil.cpu_count(logical=True) or 1
    physical = psutil.cpu_count(logical=False)

    freq_current: float | None = None
    freq_max: float | None = None
    try:
        freq = psutil.cpu_freq()
        if freq is not None:
            freq_current = float(freq.current) if freq.current else None
            freq_max = float(freq.max) if freq.max else None
    except (OSError, NotImplementedError, AttributeError) as exc:
        errors.append(f"cpu frequency unavailable: {type(exc).__name__}")

    return CpuInfo(
        model=model,
        logical_cpus=int(logical),
        physical_cores=int(physical) if physical else None,
        current_percent=round(current, 1),
        average_percent=round(average, 1),
        samples=tuple(round(s, 1) for s in samples),
        frequency_current_mhz=round(freq_current, 1) if freq_current else None,
        frequency_max_mhz=round(freq_max, 1) if freq_max else None,
        notes=tuple(errors),
    )
