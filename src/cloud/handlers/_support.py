"""Shared handler plumbing (not a route itself).

Centralises the pieces every stateful handler repeats: lazy, cached settings and
dependency construction (so a warm Lambda reuses one SSM provider and table),
one-time root-logger configuration, and small query-parameter helpers. Kept
internal to ``cloud.handlers``.
"""

from __future__ import annotations

import logging

import boto3
from botocore.config import Config

from cloud.auth import ApiKeyProvider
from cloud.errors import ValidationFailed

__all__ = [
    "configure_root_logging",
    "build_auth_provider",
    "parse_limit",
]

_SSM_CONFIG = Config(
    retries={"mode": "standard", "max_attempts": 3},
    connect_timeout=2,
    read_timeout=5,
)

_logging_configured = False


def configure_root_logging(level: str) -> None:
    """Configure the root logger once with the shared JSON formatter.

    Lambda ships stdout to CloudWatch, so a ``StreamHandler`` with
    ``JsonFormatter`` is all that is needed. Idempotent across warm invocations.
    """
    global _logging_configured
    if _logging_configured:
        logging.getLogger().setLevel(level)
        return
    from shared.utils.json_logging import JsonFormatter, RedactionFilter

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactionFilter())
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)
    _logging_configured = True


def build_auth_provider(ingest_param: str, read_param: str) -> ApiKeyProvider:
    """Create an ``ApiKeyProvider`` backed by a real SSM client."""
    ssm = boto3.client("ssm", config=_SSM_CONFIG)
    return ApiKeyProvider(ssm, ingest_param, read_param)


def parse_limit(
    raw: str | None, *, default: int, minimum: int, maximum: int
) -> int:
    """Parse and bound a ``limit`` query parameter.

    Returns ``default`` when absent. Raises ``ValidationFailed`` for a
    non-integer or out-of-range value.
    """
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValidationFailed(
            details=[{"field": "limit", "issue": "must be an integer"}]
        ) from exc
    if not (minimum <= value <= maximum):
        raise ValidationFailed(
            details=[
                {"field": "limit", "issue": f"must be between {minimum} and {maximum}"}
            ]
        )
    return value
