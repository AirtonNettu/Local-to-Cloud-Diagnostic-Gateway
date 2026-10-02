"""Network probes: ICMP ping, TCP connect and DNS resolution (design B.7).

Probes never raise: every failure maps to a ``ProbeOutcome``. No raw sockets and
no admin rights are needed (spec C6).

Key correctness points folded from the design review:
- NIT6: the ping RTT/``TTL=`` test is applied only to the reply line coming from
  the target host (a line containing ``f"{host}:"``), so a statistics block that
  happens to contain ``0ms`` can never produce a false SUCCESS for IPv6.
- NIT7: DNS resolution runs in a per-host ``threading.Thread(daemon=True)`` with
  ``join(timeout)``; a hung resolver can neither delay process exit nor starve a
  later resolution's timeout budget.
"""

from __future__ import annotations

import contextlib
import errno
import ipaddress
import re
import socket
import subprocess  # noqa: S404 - fixed argv, no shell, validated host only.
import sys
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

__all__ = [
    "ProbeOutcome",
    "ProbeResult",
    "ResolveResult",
    "Prober",
    "SystemProber",
]

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# Matches "time=2ms", "tempo=2ms", "time<1ms", "tempo<1ms" (every locale).
_RTT_RE = re.compile(r"[=<]\s*(\d+)\s*ms", re.IGNORECASE)

# Windows winsock errno values not always present in the ``errno`` module.
_WSAENETUNREACH = 10051
_WSAEHOSTUNREACH = 10065

_NO_REPLY_ERRNOS = {
    errno.ENETUNREACH,
    errno.EHOSTUNREACH,
    _WSAENETUNREACH,
    _WSAEHOSTUNREACH,
}


class ProbeOutcome(str, Enum):
    """Outcome of a single probe."""

    SUCCESS = "SUCCESS"  # reply received / connection established / name resolved
    NO_REPLY = "NO_REPLY"  # executed; timeout, refused, unreachable, NXDOMAIN
    ERROR = "ERROR"  # could not execute (ping.exe missing, socket creation failed)


@dataclass(frozen=True)
class ProbeResult:
    """Result of a ping or TCP-connect probe."""

    target: str
    outcome: ProbeOutcome
    rtt_ms: float | None
    detail: str


@dataclass(frozen=True)
class ResolveResult:
    """Result of a DNS resolution."""

    hostname: str
    outcome: ProbeOutcome
    addresses: tuple[str, ...]
    duration_ms: float | None


@runtime_checkable
class Prober(Protocol):
    """Network probe surface (implementations never raise)."""

    def icmp_ping(self, host: str, timeout_s: float) -> ProbeResult: ...

    def tcp_connect(self, host: str, port: int, timeout_s: float) -> ProbeResult: ...

    def resolve(self, hostname: str, timeout_s: float) -> ResolveResult: ...


def _is_ipv6(host: str) -> bool:
    try:
        return isinstance(ipaddress.ip_address(host), ipaddress.IPv6Address)
    except ValueError:
        return False


def _parse_ping(host: str, stdout: str, is_ipv6: bool) -> tuple[bool, float | None]:
    """Return ``(success, rtt_ms)`` applying the NIT6 target-line rule.

    A line counts as a reply from the target only when it contains ``f"{host}:"``.
    IPv4 success additionally requires ``TTL=`` on that line; IPv6 success
    requires an RTT match on that line (IPv6 replies carry no ``TTL=``).
    """
    needle = f"{host}:"
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if needle not in line:
            continue
        upper = line.upper()
        rtt_match = _RTT_RE.search(line)
        rtt = float(rtt_match.group(1)) if rtt_match else None
        if is_ipv6:
            if rtt_match is not None:
                return True, rtt
        else:
            if "TTL=" in upper:
                return True, rtt
    return False, None


class SystemProber:
    """Prober using the system ``ping`` and the stdlib socket API (design B.7)."""

    def icmp_ping(self, host: str, timeout_s: float) -> ProbeResult:
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return ProbeResult(host, ProbeOutcome.ERROR, None, "host is not an IP")

        is_ipv6 = _is_ipv6(host)
        timeout_ms = max(1, int(timeout_s * 1000))
        argv = ["ping", "-n", "1", "-w", str(timeout_ms)]
        if is_ipv6:
            argv.append("-6")
        argv.append(host)
        try:
            completed = subprocess.run(  # noqa: S603 - fixed argv, validated host.
                argv,
                capture_output=True,
                text=True,
                timeout=timeout_s + 2,
                creationflags=_CREATE_NO_WINDOW,
                check=False,
            )
        except (FileNotFoundError, OSError) as exc:
            return ProbeResult(
                host, ProbeOutcome.ERROR, None, f"ping failed: {type(exc).__name__}"
            )
        except subprocess.TimeoutExpired:
            return ProbeResult(host, ProbeOutcome.NO_REPLY, None, "ping timed out")

        if completed.returncode != 0:
            return ProbeResult(host, ProbeOutcome.NO_REPLY, None, "no reply")
        success, rtt = _parse_ping(host, completed.stdout or "", is_ipv6)
        if success:
            detail = f"reply in {rtt:.0f} ms" if rtt is not None else "reply received"
            return ProbeResult(host, ProbeOutcome.SUCCESS, rtt, detail)
        return ProbeResult(host, ProbeOutcome.NO_REPLY, None, "no reply from target")

    def tcp_connect(self, host: str, port: int, timeout_s: float) -> ProbeResult:
        start = time.perf_counter()
        try:
            conn = socket.create_connection((host, port), timeout=timeout_s)
        except (
            socket.gaierror,
            TimeoutError,
            ConnectionRefusedError,
            ConnectionResetError,
        ) as exc:
            return ProbeResult(
                host, ProbeOutcome.NO_REPLY, None, f"{type(exc).__name__}"
            )
        except OSError as exc:
            if exc.errno in _NO_REPLY_ERRNOS:
                return ProbeResult(
                    host, ProbeOutcome.NO_REPLY, None, f"{type(exc).__name__}"
                )
            return ProbeResult(
                host, ProbeOutcome.ERROR, None, f"{type(exc).__name__}"
            )
        rtt_ms = (time.perf_counter() - start) * 1000
        with contextlib.suppress(OSError):
            conn.close()
        return ProbeResult(
            host,
            ProbeOutcome.SUCCESS,
            round(rtt_ms, 1),
            f"connected in {rtt_ms:.0f} ms",
        )

    def resolve(self, hostname: str, timeout_s: float) -> ResolveResult:
        addresses: list[str] = []
        holder: dict[str, bool] = {}

        def _worker() -> None:
            try:
                infos = socket.getaddrinfo(hostname, None)
                addresses.extend(sorted({str(info[4][0]) for info in infos}))
            except socket.gaierror:  # NXDOMAIN / no address
                holder["gaierror"] = True
            except OSError:
                holder["oserror"] = True

        start = time.perf_counter()
        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        thread.join(timeout_s)
        duration_ms = (time.perf_counter() - start) * 1000

        if thread.is_alive():
            # The daemon thread finishes in the background; we time out here.
            return ResolveResult(hostname, ProbeOutcome.NO_REPLY, (), None)
        rounded = round(duration_ms, 1)
        # Same specific-first ordering rule as TCP: gaierror -> NO_REPLY.
        if "gaierror" in holder:
            return ResolveResult(hostname, ProbeOutcome.NO_REPLY, (), rounded)
        if "oserror" in holder:
            return ResolveResult(hostname, ProbeOutcome.ERROR, (), rounded)
        return ResolveResult(
            hostname, ProbeOutcome.SUCCESS, tuple(addresses), rounded
        )
