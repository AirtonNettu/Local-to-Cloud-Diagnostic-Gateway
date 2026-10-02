"""Tests for CLI parsing, help, and version (foundation skeleton)."""

from __future__ import annotations

import pytest

from agent import __version__
from agent.main import build_parser, main

_COMMANDS = (
    "scan",
    "hardware",
    "network",
    "health",
    "sync",
    "status",
    "queue",
    "demo",
    "run",
)


def test_help_lists_all_commands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for command in _COMMANDS:
        assert command in out


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_no_command_prints_help_and_exits_usage() -> None:
    assert main([]) == 2


def test_each_command_has_help(capsys: pytest.CaptureFixture[str]) -> None:
    for command in _COMMANDS:
        with pytest.raises(SystemExit) as exc:
            main([command, "--help"])
        assert exc.value.code == 0
        capsys.readouterr()


def test_parser_builds() -> None:
    parser = build_parser()
    args = parser.parse_args(["scan", "--sync", "--json"])
    assert args.command == "scan"
    assert args.sync is True
    assert args.json is True


def test_global_log_level_choice() -> None:
    args = build_parser().parse_args(["--log-level", "DEBUG", "status"])
    assert args.log_level == "DEBUG"


def test_health_json_flag_parses() -> None:
    args = build_parser().parse_args(["health", "--json"])
    assert args.command == "health"
    assert args.json is True


def test_network_and_hardware_json_flags_parse() -> None:
    for command in ("network", "hardware"):
        args = build_parser().parse_args([command, "--json"])
        assert args.command == command
        assert args.json is True
