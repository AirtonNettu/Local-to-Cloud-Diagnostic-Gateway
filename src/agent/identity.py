"""Device identity resolution (design B.5).

The device identity is a random UUIDv4 generated on first run and stored in the
``devices`` table with ``is_local = 1``; the hostname is a stored attribute,
never the key. A ``DEVICE_ID`` override is stored with ``is_local = 0`` so the
foreign keys in ``diagnostic_runs``/``sync_queue`` hold. A partial unique index
(``idx_devices_single_local``) guarantees at most one ``is_local = 1`` row.

``resolve_device_id`` is the single resolution point. ``create=True`` requires a
writable connection; read-only callers pass ``create=False`` (and either a
read-only connection or ``None`` when the database file does not exist).
"""

from __future__ import annotations

import platform
import sqlite3
import uuid

from agent.config.settings import Settings
from shared.utils.timeutil import to_iso, utc_now

__all__ = ["resolve_device_id"]


def resolve_device_id(
    conn: sqlite3.Connection | None, settings: Settings, *, create: bool
) -> str | None:
    """Return the device id, writing it when ``create`` is True.

    Resolution order (design B.5):
      1. ``DEVICE_ID`` override. ``create=True`` upserts it with ``is_local=0``
         and returns it; ``create=False`` returns it without writing.
      2. The stored ``is_local=1`` row, if any.
      3. ``create=True``: generate a UUIDv4, insert it with ``is_local=1`` and
         return it. ``create=False``: return ``None``.
    """
    override = settings.device_id.strip()
    if override:
        if create:
            if conn is None:
                raise ValueError("create=True requires a writable connection")
            _upsert_override(conn, settings, override)
        return override

    if conn is not None:
        stored = _stored_local_id(conn)
        if stored is not None:
            return stored

    if not create:
        return None
    if conn is None:
        raise ValueError("create=True requires a writable connection")
    generated = str(uuid.uuid4())
    _insert_local(conn, settings, generated)
    return generated


def _device_name(settings: Settings) -> str:
    return settings.device_name.strip() or platform.node() or "unknown"


def _hostname() -> str:
    return platform.node() or "unknown"


def _upsert_override(
    conn: sqlite3.Connection, settings: Settings, device_id: str
) -> None:
    now = to_iso(utc_now())
    conn.execute(
        """
        INSERT INTO devices (device_id, device_name, hostname, is_local, created_at)
        VALUES (?, ?, ?, 0, ?)
        ON CONFLICT(device_id) DO UPDATE SET
            device_name = excluded.device_name,
            hostname = excluded.hostname,
            is_local = 0
        """,
        (device_id, _device_name(settings), _hostname(), now),
    )
    conn.commit()


def _stored_local_id(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT device_id FROM devices WHERE is_local = 1 LIMIT 1"
    ).fetchone()
    return str(row[0]) if row is not None else None


def _insert_local(
    conn: sqlite3.Connection, settings: Settings, device_id: str
) -> None:
    now = to_iso(utc_now())
    conn.execute(
        """
        INSERT INTO devices (device_id, device_name, hostname, is_local, created_at)
        VALUES (?, ?, ?, 1, ?)
        """,
        (device_id, _device_name(settings), _hostname(), now),
    )
    conn.commit()
