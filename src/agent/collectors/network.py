"""Network collector (design B.6).

Interfaces come from psutil; ``AF_LINK`` (MAC) entries are deliberately ignored
(privacy). Gateways and DNS come from the platform module. ``None`` for
gateways/DNS means the platform query failed or is unavailable (status PARTIAL);
``[]`` means the query succeeded and there is none (e.g. cable unplugged). That
distinction drives the network rules.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass

import psutil

from agent.collectors.base import PartialCollection
from agent.platform_support.base import (
    PlatformInfo,
    PlatformQueryError,
    PlatformUnavailableError,
)

__all__ = ["InterfaceInfo", "NetworkInfo", "collect_network"]


@dataclass(frozen=True)
class InterfaceInfo:
    """One network interface and its addresses (no MAC)."""

    name: str
    is_up: bool
    speed_mbps: int | None
    ipv4: tuple[str, ...]
    ipv6: tuple[str, ...]


@dataclass(frozen=True)
class NetworkInfo:
    """Host network facts: interfaces, gateways and DNS servers."""

    hostname: str
    interfaces: tuple[InterfaceInfo, ...]
    gateways: tuple[str, ...] | None
    dns_servers: tuple[str, ...] | None


def _collect_interfaces() -> list[InterfaceInfo]:
    addrs = psutil.net_if_addrs()
    stats = psutil.net_if_stats()
    interfaces: list[InterfaceInfo] = []
    for name, addr_list in addrs.items():
        ipv4: list[str] = []
        ipv6: list[str] = []
        for addr in addr_list:
            if addr.family == socket.AF_INET:
                ipv4.append(addr.address)
            elif addr.family == socket.AF_INET6:
                # Strip the scope id (e.g. "fe80::1%12").
                ipv6.append(addr.address.split("%", 1)[0])
            # AF_LINK (MAC) and anything else is deliberately ignored.
        stat = stats.get(name)
        is_up = bool(stat.isup) if stat is not None else False
        speed = int(stat.speed) if stat is not None and stat.speed else None
        interfaces.append(
            InterfaceInfo(
                name=name,
                is_up=is_up,
                speed_mbps=speed,
                ipv4=tuple(ipv4),
                ipv6=tuple(ipv6),
            )
        )
    return interfaces


def collect_network(platform_info: PlatformInfo) -> NetworkInfo:
    """Collect interfaces, gateways and DNS; PARTIAL if the platform query fails."""
    interfaces = _collect_interfaces()
    hostname = socket.gethostname() or "unknown"

    gateways: tuple[str, ...] | None
    dns_servers: tuple[str, ...] | None
    errors: list[str] = []
    try:
        gw, dns = platform_info.network_config()
        gateways = tuple(gw)
        dns_servers = tuple(dns)
    except (PlatformUnavailableError, PlatformQueryError) as exc:
        gateways = None
        dns_servers = None
        errors.append(f"network config unavailable: {type(exc).__name__}")

    info = NetworkInfo(
        hostname=hostname,
        interfaces=tuple(interfaces),
        gateways=gateways,
        dns_servers=dns_servers,
    )
    if errors:
        raise PartialCollection(info, errors)
    return info
