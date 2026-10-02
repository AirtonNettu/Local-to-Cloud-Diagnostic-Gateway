"""Storage collector (design B.6).

Enumerates fixed volumes and their usage. Partitions whose ``opts`` mark them
``cdrom`` or ``remote`` are skipped *before* calling ``disk_usage`` so a
disconnected mapped network drive can never block an offline scan, regardless of
psutil's own filtering. A volume whose ``disk_usage`` raises ``OSError`` (e.g. an
empty card reader) is recorded as a partial error, not a failure.
"""

from __future__ import annotations

from dataclasses import dataclass

import psutil

from agent.collectors.base import PartialCollection

__all__ = ["VolumeInfo", "collect_storage"]


@dataclass(frozen=True)
class VolumeInfo:
    """One mounted volume and its usage."""

    device: str
    mountpoint: str
    filesystem: str
    total_bytes: int
    free_bytes: int
    used_bytes: int
    percent: float


_SKIP_OPTS = ("cdrom", "remote")


def _should_skip(opts: str) -> bool:
    tokens = {token.strip().lower() for token in opts.split(",")}
    return any(skip in tokens for skip in _SKIP_OPTS)


def collect_storage() -> list[VolumeInfo]:
    """Collect per-volume usage, skipping removable/remote and unreadable mounts."""
    volumes: list[VolumeInfo] = []
    errors: list[str] = []
    for part in psutil.disk_partitions(all=False):
        if _should_skip(part.opts or ""):
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (OSError, PermissionError) as exc:
            errors.append(f"{part.mountpoint}: {type(exc).__name__}")
            continue
        volumes.append(
            VolumeInfo(
                device=part.device,
                mountpoint=part.mountpoint,
                filesystem=part.fstype or "unknown",
                total_bytes=int(usage.total),
                free_bytes=int(usage.free),
                used_bytes=int(usage.used),
                percent=round(float(usage.percent), 1),
            )
        )
    if errors:
        raise PartialCollection(volumes, errors)
    return volumes
