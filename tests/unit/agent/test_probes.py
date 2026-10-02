"""Tests for SystemProber: ping parsing (NIT6), TCP and DNS ordering."""

from __future__ import annotations

import errno
import socket
import subprocess
from pathlib import Path

import pytest

from agent.diagnostics import probes
from agent.diagnostics.probes import ProbeOutcome, SystemProber

_PING = Path(__file__).resolve().parents[2] / "fixtures" / "ping"


class _Completed:
    def __init__(self, returncode: int, stdout: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def _fixture(name: str) -> str:
    return (_PING / name).read_text(encoding="utf-8")


def _patch_ping(monkeypatch: pytest.MonkeyPatch, returncode: int, stdout: str) -> None:
    monkeypatch.setattr(
        probes.subprocess,
        "run",
        lambda *a, **k: _Completed(returncode, stdout),
    )


def test_ipv4_success_en(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_ping(monkeypatch, 0, _fixture("ipv4_success_en.txt"))
    result = SystemProber().icmp_ping("1.1.1.1", 2.0)
    assert result.outcome is ProbeOutcome.SUCCESS
    assert result.rtt_ms == 12.0


def test_ipv4_success_ptbr(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_ping(monkeypatch, 0, _fixture("ipv4_success_ptbr.txt"))
    result = SystemProber().icmp_ping("10.0.0.1", 2.0)
    assert result.outcome is ProbeOutcome.SUCCESS
    # "tempo<1ms" parses to 1 via the [=<]\s*(\d+)\s*ms regex.
    assert result.rtt_ms == 1.0


def test_ipv4_unreachable_rc0_is_no_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    # Windows returns rc 0 for "destination host unreachable"; the reply line
    # comes from the router, not the target, and lacks TTL= on the target line.
    _patch_ping(monkeypatch, 0, _fixture("ipv4_unreachable_en.txt"))
    result = SystemProber().icmp_ping("192.0.2.1", 2.0)
    assert result.outcome is ProbeOutcome.NO_REPLY


def test_ipv4_timeout_ptbr(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_ping(monkeypatch, 1, _fixture("ipv4_timeout_ptbr.txt"))
    result = SystemProber().icmp_ping("192.0.2.1", 2.0)
    assert result.outcome is ProbeOutcome.NO_REPLY


def test_ipv6_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_ping(monkeypatch, 0, _fixture("ipv6_success_en.txt"))
    result = SystemProber().icmp_ping("2606:4700:4700::1111", 2.0)
    assert result.outcome is ProbeOutcome.SUCCESS
    assert result.rtt_ms == 15.0


def test_ipv6_unreachable_with_stats_block_is_no_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # NIT6: statistics block has "0ms" but no echo from the target host -> the
    # RTT regex must only apply to the target reply line, so this is NO_REPLY.
    _patch_ping(monkeypatch, 0, _fixture("ipv6_unreachable_stats_ptbr.txt"))
    result = SystemProber().icmp_ping("2606:4700:4700::1111", 2.0)
    assert result.outcome is ProbeOutcome.NO_REPLY


def test_ping_filenotfound_is_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*a: object, **k: object) -> object:
        raise FileNotFoundError("no ping")

    monkeypatch.setattr(probes.subprocess, "run", _raise)
    result = SystemProber().icmp_ping("1.1.1.1", 2.0)
    assert result.outcome is ProbeOutcome.ERROR


def test_ping_rejects_non_ip() -> None:
    result = SystemProber().icmp_ping("example.com", 2.0)
    assert result.outcome is ProbeOutcome.ERROR


def test_ping_timeout_expired_is_no_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*a: object, **k: object) -> object:
        raise subprocess.TimeoutExpired(cmd="ping", timeout=2.0)

    monkeypatch.setattr(probes.subprocess, "run", _raise)
    result = SystemProber().icmp_ping("1.1.1.1", 2.0)
    assert result.outcome is ProbeOutcome.NO_REPLY


# --- TCP ordering ---------------------------------------------------------


def test_tcp_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Conn:
        def close(self) -> None:
            pass

    monkeypatch.setattr(probes.socket, "create_connection", lambda *a, **k: _Conn())
    result = SystemProber().tcp_connect("1.1.1.1", 443, 2.0)
    assert result.outcome is ProbeOutcome.SUCCESS
    assert result.rtt_ms is not None


def test_tcp_gaierror_is_no_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*a: object, **k: object) -> object:
        raise socket.gaierror("name resolution failed")

    monkeypatch.setattr(probes.socket, "create_connection", _raise)
    result = SystemProber().tcp_connect("bad.host", 443, 2.0)
    assert result.outcome is ProbeOutcome.NO_REPLY


def test_tcp_refused_is_no_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*a: object, **k: object) -> object:
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr(probes.socket, "create_connection", _raise)
    result = SystemProber().tcp_connect("1.1.1.1", 443, 2.0)
    assert result.outcome is ProbeOutcome.NO_REPLY


def test_tcp_eacces_is_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*a: object, **k: object) -> object:
        raise OSError(errno.EACCES, "simulated")

    monkeypatch.setattr(probes.socket, "create_connection", _raise)
    result = SystemProber().tcp_connect("1.1.1.1", 443, 2.0)
    assert result.outcome is ProbeOutcome.ERROR


def test_tcp_enetunreach_is_no_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*a: object, **k: object) -> object:
        raise OSError(errno.ENETUNREACH, "unreachable")

    monkeypatch.setattr(probes.socket, "create_connection", _raise)
    result = SystemProber().tcp_connect("1.1.1.1", 443, 2.0)
    assert result.outcome is ProbeOutcome.NO_REPLY


# --- DNS ordering ---------------------------------------------------------


def test_dns_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        probes.socket,
        "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )
    result = SystemProber().resolve("example.com", 2.0)
    assert result.outcome is ProbeOutcome.SUCCESS
    assert "93.184.216.34" in result.addresses


def test_dns_gaierror_is_no_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*a: object, **k: object) -> object:
        raise socket.gaierror("NXDOMAIN")

    monkeypatch.setattr(probes.socket, "getaddrinfo", _raise)
    result = SystemProber().resolve("nope.invalid", 2.0)
    assert result.outcome is ProbeOutcome.NO_REPLY


def test_dns_eacces_is_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*a: object, **k: object) -> object:
        raise OSError(errno.EACCES, "simulated")

    monkeypatch.setattr(probes.socket, "getaddrinfo", _raise)
    result = SystemProber().resolve("example.com", 2.0)
    assert result.outcome is ProbeOutcome.ERROR
