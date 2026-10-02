"""Tests for the interactive ``menu`` subcommand (design: looping dispatch).

The menu reads input through the injected ``_input`` seam and writes through
``_print``, mirroring the ``_sleep``/``_monotonic`` convention used by
``cmd_run``. Handlers are replaced with spies via ``monkeypatch.setattr`` the
same way ``test_cli_exit_codes.py`` injects ``build_api_client``.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator

import pytest

from agent import commands
from agent.main import main


def _menu_args(inputs: Iterator[str]) -> argparse.Namespace:
    """A menu namespace driven by a scripted iterator of input lines."""

    def scripted_input(_prompt: str) -> str:
        return next(inputs)

    return argparse.Namespace(
        command="menu",
        log_level=None,
        env_file=None,
        _input=scripted_input,
    )


def test_menu_help_registered(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["menu", "--help"])
    assert exc.value.code == 0
    assert "menu" in capsys.readouterr().out


def test_valid_choice_dispatches_then_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_health(args: argparse.Namespace) -> int:
        calls.append("health")
        return 0

    monkeypatch.setattr(commands, "cmd_health", fake_health)
    args = _menu_args(iter(["2", "0"]))
    assert commands.cmd_menu(args) == 0
    assert calls == ["health"]


def test_invalid_input_reprompts_without_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    for name in ("cmd_scan", "cmd_health", "cmd_hardware", "cmd_network",
                 "cmd_status", "cmd_queue_stats", "cmd_sync", "cmd_demo"):
        monkeypatch.setattr(
            commands, name, lambda _a, _n=name: (calls.append(_n), 0)[1]
        )
    # Non-numeric, out-of-range, empty: all re-prompt, none dispatch.
    args = _menu_args(iter(["x", "99", "", "0"]))
    assert commands.cmd_menu(args) == 0
    assert calls == []


def test_eof_exits_cleanly() -> None:
    def eof_input(_prompt: str) -> str:
        raise EOFError

    args = argparse.Namespace(
        command="menu", log_level=None, env_file=None, _input=eof_input
    )
    assert commands.cmd_menu(args) == 0


def test_nonzero_handler_does_not_abort_loop(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []

    def failing_status(_args: argparse.Namespace) -> int:
        calls.append("status")
        return 1

    monkeypatch.setattr(commands, "cmd_status", failing_status)
    # Choose Status (fails), then Exit. The menu must be shown again and the
    # final return code is 0, not the handler's 1.
    args = _menu_args(iter(["5", "0"]))
    assert commands.cmd_menu(args) == 0
    assert calls == ["status"]
    out = capsys.readouterr().out
    # The menu header appears twice: once before the action, once after.
    assert out.count("Diagnostic Gateway menu") == 2
    assert "exited with code 1" in out
