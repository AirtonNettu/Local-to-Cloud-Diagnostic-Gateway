"""Shared pytest fixtures and safety guards.

An autouse fixture sets fake AWS credentials and region so no test can ever
reach a real AWS account, and provides a temporary database path, a fixed clock
and a seeded random generator for deterministic tests.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def fake_aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force fake AWS credentials and region; never touch a real account."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.delenv("AWS_PROFILE", raising=False)


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Return a path to a temporary SQLite database file."""
    return tmp_path / "agent.db"


class FixedClock:
    """A deterministic clock returning a fixed timezone-aware UTC datetime."""

    def __init__(self, moment: datetime | None = None) -> None:
        self._moment = moment or datetime(2024, 1, 2, 3, 4, 5, 678000, tzinfo=UTC)

    def now(self) -> datetime:
        return self._moment


@pytest.fixture
def fixed_clock() -> FixedClock:
    return FixedClock()


@pytest.fixture
def seeded_random() -> Iterator[random.Random]:
    yield random.Random(1234)
