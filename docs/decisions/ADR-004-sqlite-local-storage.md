# ADR-004: SQLite for local storage

> Language: English · [Português (Brasil)](ADR-004-sqlite-local-storage.pt-BR.md)

Status: accepted.

## Context

The local-first design (ADR-001) needs durable, transactional, zero-setup
storage for runs, results and the sync queue on a user's machine, with no server
to install and no extra dependency.

## Decision

Use the standard-library `sqlite3` module in WAL mode with foreign keys on.
Migrations are keyed by `PRAGMA user_version`; `PRAGMA application_id` marks live
versus demo databases so demo mode never deletes a file it did not create. Each
run persists its row, results and (optionally) a queue event in one
`BEGIN IMMEDIATE` transaction. Read-only commands open a `mode=ro` URI and never
migrate.

## Alternatives

- **Flat files (JSON/CSV)**: no transactions or concurrent-safe queue; would
  reinvent locking. Rejected.
- **An embedded server (e.g. local Postgres)**: install and run a server on an
  edge machine. Rejected.

## Consequences

- No third-party dependency and no setup; the file is the database.
- Atomic persistence guarantees the run/queue invariant.
- Concurrency is bounded by SQLite's single-writer model, which is sufficient
  for one agent process; a locked database surfaces as a clean exit-1 error.
