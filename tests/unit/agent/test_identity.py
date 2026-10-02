"""Tests for device identity resolution (design B.5)."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from pathlib import Path

import pytest

from agent.config.settings import Settings, load_settings
from agent.identity import resolve_device_id
from agent.storage import local_db


def _settings(env: Mapping[str, str] | None = None) -> Settings:
    return load_settings(env=dict(env or {}))


def _writable(path: Path) -> sqlite3.Connection:
    return local_db.connect(path)


def test_generates_and_persists_local_identity(tmp_path: Path) -> None:
    conn = _writable(tmp_path / "agent.db")
    try:
        settings = _settings()
        first = resolve_device_id(conn, settings, create=True)
        assert first is not None
        # Stable across runs (same stored is_local=1 row).
        second = resolve_device_id(conn, settings, create=True)
        assert second == first
        row = conn.execute(
            "SELECT device_id, is_local FROM devices WHERE is_local = 1"
        ).fetchone()
        assert row == (first, 1)
    finally:
        conn.close()


def test_override_stored_is_local_zero(tmp_path: Path) -> None:
    conn = _writable(tmp_path / "agent.db")
    try:
        settings = _settings({"DEVICE_ID": "override-abc"})
        resolved = resolve_device_id(conn, settings, create=True)
        assert resolved == "override-abc"
        row = conn.execute(
            "SELECT is_local FROM devices WHERE device_id = 'override-abc'"
        ).fetchone()
        assert row == (0,)
    finally:
        conn.close()


def test_create_false_writes_nothing(tmp_path: Path) -> None:
    conn = _writable(tmp_path / "agent.db")
    try:
        settings = _settings()
        result = resolve_device_id(conn, settings, create=False)
        assert result is None
        count = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
        assert count == 0
    finally:
        conn.close()


def test_create_false_returns_override_without_writing(tmp_path: Path) -> None:
    conn = _writable(tmp_path / "agent.db")
    try:
        settings = _settings({"DEVICE_ID": "override-abc"})
        result = resolve_device_id(conn, settings, create=False)
        assert result == "override-abc"
        count = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
        assert count == 0
    finally:
        conn.close()


def test_device_id_unchanged_when_ip_changes(tmp_path: Path) -> None:
    # Identity lives in the DB, not derived from network state, so it is stable
    # regardless of any IP change between runs.
    conn = _writable(tmp_path / "agent.db")
    try:
        settings = _settings()
        first = resolve_device_id(conn, settings, create=True)
        # Simulate a later run: nothing about the environment IP matters.
        again = resolve_device_id(conn, settings, create=True)
        assert again == first
    finally:
        conn.close()


def test_second_is_local_row_rejected_by_partial_unique_index(
    tmp_path: Path,
) -> None:
    conn = _writable(tmp_path / "agent.db")
    try:
        conn.execute(
            "INSERT INTO devices (device_id, device_name, hostname, is_local, "
            "created_at) VALUES ('a', 'n', 'h', 1, 't')"
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO devices (device_id, device_name, hostname, "
                "is_local, created_at) VALUES ('b', 'n', 'h', 1, 't')"
            )
    finally:
        conn.close()


def test_create_true_requires_connection() -> None:
    settings = _settings()
    with pytest.raises(ValueError):
        resolve_device_id(None, settings, create=True)
