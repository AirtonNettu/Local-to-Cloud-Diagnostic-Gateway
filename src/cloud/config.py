"""Per-handler configuration loading (design B.14).

Each handler module declares its own ``REQUIRED_ENV`` and calls
``CloudSettings.load(required=REQUIRED_ENV)`` lazily on first invocation, so a
function only reads the variables it actually needs (finding F8). A missing
required variable raises ``RuntimeError`` naming it; the handler lets that
surface as a Lambda error (500) so the misconfiguration is loud. ``LOG_LEVEL``
and ``SERVICE_VERSION`` are optional everywhere; fields not in ``required`` are
``None``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

__all__ = ["CloudSettings"]

# Variables a handler may request through ``required``.
_LOADABLE = frozenset(
    {
        "TABLE_NAME",
        "INGEST_KEY_PARAMETER",
        "READ_KEY_PARAMETER",
        "DIAGNOSTIC_RETENTION_DAYS",
    }
)

_DEFAULT_LOG_LEVEL = "INFO"
_DEFAULT_SERVICE_VERSION = "0.0.0"


@dataclass(frozen=True)
class CloudSettings:
    """Resolved configuration for one handler invocation.

    Only the variables named in ``required`` are guaranteed non-``None``; the
    rest stay ``None``. ``log_level`` and ``service_version`` always have a
    value (defaults applied).
    """

    log_level: str
    service_version: str
    table_name: str | None = None
    ingest_key_parameter: str | None = None
    read_key_parameter: str | None = None
    diagnostic_retention_days: int | None = None

    @classmethod
    def load(
        cls,
        required: frozenset[str],
        env: Mapping[str, str] = os.environ,
    ) -> CloudSettings:
        """Build settings, requiring every variable named in ``required``.

        Raises ``RuntimeError`` naming the first missing or invalid required
        variable (fatal misconfiguration). ``required`` must be a subset of the
        loadable variable names.
        """
        unknown = required - _LOADABLE
        if unknown:
            raise RuntimeError(
                f"unknown required variable(s): {', '.join(sorted(unknown))}"
            )

        retention: int | None = None
        if "DIAGNOSTIC_RETENTION_DAYS" in required:
            raw = _require(env, "DIAGNOSTIC_RETENTION_DAYS")
            try:
                retention = int(raw)
            except ValueError as exc:
                raise RuntimeError(
                    "DIAGNOSTIC_RETENTION_DAYS must be an integer"
                ) from exc
            if retention < 1:
                raise RuntimeError("DIAGNOSTIC_RETENTION_DAYS must be >= 1")

        return cls(
            log_level=env.get("LOG_LEVEL", _DEFAULT_LOG_LEVEL),
            service_version=env.get("SERVICE_VERSION", _DEFAULT_SERVICE_VERSION),
            table_name=(
                _require(env, "TABLE_NAME") if "TABLE_NAME" in required else None
            ),
            ingest_key_parameter=(
                _require(env, "INGEST_KEY_PARAMETER")
                if "INGEST_KEY_PARAMETER" in required
                else None
            ),
            read_key_parameter=(
                _require(env, "READ_KEY_PARAMETER")
                if "READ_KEY_PARAMETER" in required
                else None
            ),
            diagnostic_retention_days=retention,
        )


def _require(env: Mapping[str, str], name: str) -> str:
    value = env.get(name)
    if value is None or value == "":
        raise RuntimeError(f"required environment variable {name} is not set")
    return value
