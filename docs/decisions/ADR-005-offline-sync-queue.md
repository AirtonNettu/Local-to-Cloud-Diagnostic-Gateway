# ADR-005: Offline sync queue

> Language: English · [Português (Brasil)](ADR-005-offline-sync-queue.pt-BR.md)

Status: accepted.

## Context

Because diagnostics run offline (ADR-001), results must survive long outages and
reach the cloud exactly once when connectivity returns, without a busy loop and
without losing or duplicating events.

## Decision

Persist each event in a `sync_queue` table with an explicit state machine:
`PENDING → SYNCING → (SYNCED | FAILED | DEAD_LETTER)`. A sync cycle claims due
events, delivers byte-packed batches, and records every attempt in
`sync_attempts`. Delivered-but-failed requests back off (exponential with
jitter) and dead-letter at `RETRY_LIMIT`. A request that was provably not
delivered is recorded as an `OFFLINE` attempt and does **not** consume the retry
budget, so being offline — the product's normal condition — never dead-letters
an event. Aggressiveness during an outage is bounded by the cycle cadence (one
connection attempt per cycle, no in-process retry loop).

## Alternatives

- **Count offline cycles against the retry limit**: would dead-letter events
  during normal outages, defeating the purpose. Rejected.
- **An in-process retry loop**: hammers the network and the API during an
  outage. Rejected in favour of per-cycle attempts.
- **An external broker (SQS on the device)**: adds a dependency and a network
  requirement to a local queue. Rejected.

## Consequences

- Events are never lost during an outage and sync resumes automatically.
- A misconfigured, non-resolving `API_BASE_URL` keeps events PENDING forever
  rather than dead-lettering; `status` makes this visible (see
  [troubleshooting.md](../troubleshooting.md)).
- Crash recovery reclaims expired `SYNCING` leases as `INTERRUPTED` attempts.
