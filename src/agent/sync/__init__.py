"""Offline sync subsystem: queue state machine, backoff, serializer and client.

This package is imported only by the sync-aware commands (``sync``, ``queue``,
``run``, ``scan --sync``) and never by the read-only diagnostic path, so the
local-first import boundary holds (design B.18). ``SyncSettings`` lives in
``agent.config.settings`` precisely so importing settings never pulls this in.
"""
