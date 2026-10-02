"""The only subprocess-to-PowerShell gateway (design B.6).

``run_powershell_json`` runs a module-level constant script and parses its
compressed JSON output. No caller-supplied text is ever interpolated into a
script, so the surface is injection-safe by construction. Failures are mapped:

- ``FileNotFoundError`` (powershell.exe missing) -> ``PlatformUnavailableError``.
- timeout / non-zero exit / empty or invalid JSON -> ``PlatformQueryError``.

A single JSON object is normalized to a one-element list so callers always
iterate.
"""

from __future__ import annotations

import json
import subprocess  # noqa: S404 - fixed argv, no shell, constant scripts only.
import sys
from typing import Any

from agent.platform_support.base import (
    PlatformQueryError,
    PlatformUnavailableError,
)

__all__ = ["run_powershell_json"]

# Hide the console window when launched from a GUI/service context (Windows).
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# Force UTF-8 output so locale-specific code pages cannot corrupt the JSON.
_UTF8_PREFIX = "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"

_MAX_STDERR_CHARS = 200


def run_powershell_json(script: str, timeout_s: float = 15.0) -> list[Any]:
    """Run ``script`` under PowerShell and return parsed JSON as a list.

    ``script`` must be a module-level constant that ends in a
    ``ConvertTo-Json`` pipeline; it is never built from caller input.
    """
    command = _UTF8_PREFIX + script
    argv = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        command,
    ]
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, shell=False.
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout_s,
            creationflags=_CREATE_NO_WINDOW,
            check=False,
        )
    except FileNotFoundError as exc:
        raise PlatformUnavailableError("powershell.exe not found") from exc
    except OSError as exc:  # pragma: no cover - rare spawn failure.
        raise PlatformQueryError(f"failed to run powershell: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise PlatformQueryError("powershell query timed out") from exc

    if completed.returncode != 0:
        detail = (completed.stderr or "").strip()[:_MAX_STDERR_CHARS]
        raise PlatformQueryError(
            f"powershell exited with code {completed.returncode}: {detail}"
        )

    stdout = (completed.stdout or "").strip()
    if not stdout:
        raise PlatformQueryError("powershell produced no output")

    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise PlatformQueryError(f"invalid JSON from powershell: {exc}") from exc

    if parsed is None:
        return []
    if isinstance(parsed, list):
        return parsed
    return [parsed]
