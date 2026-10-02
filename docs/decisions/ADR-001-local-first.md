# ADR-001: Local-first diagnostics

> Language: English · [Português (Brasil)](ADR-001-local-first.pt-BR.md)

Status: accepted.

## Context

The agent diagnoses machines that may themselves have degraded or absent
connectivity. A cloud-dependent design stops being useful exactly when it is
needed most, and uploading before persisting risks losing results during an
outage.

## Decision

Diagnostics, health evaluation and persistence run entirely on the local host
with no network dependency. Every local command (`hardware`, `network`,
`health`, `scan`, `status`, `queue`, `demo`) works offline. Sync is a separate,
optional step that reads an already-persisted queue; its failures never alter
the diagnostic result. Persistence and enqueue happen in one local transaction
before any sync.

## Alternatives

- **Cloud-first (upload then store)**: simpler data path but loses data during
  outages and couples diagnostics to connectivity. Rejected.
- **Cloud-only (no local store)**: no offline capability at all. Rejected.

## Consequences

- The agent is useful on an isolated machine; results are never lost.
- A durable local queue and a sync state machine are required (ADR-005).
- Runs recorded while sync is disabled are local-only and not back-filled, which
  is a deliberate data-minimization choice.
