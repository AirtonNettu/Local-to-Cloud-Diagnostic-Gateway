# ADR-003: Cloud database choice (DynamoDB)

> Language: English · [Português (Brasil)](ADR-003-database-choice.pt-BR.md)

Status: accepted.

## Context

The cloud store must be serverless, pay-per-use, durable, and support a small,
well-known set of key-based access patterns (register/read a device, list
devices, ingest an idempotent event, read recent diagnostics). It must expire
old data automatically and avoid capacity planning.

## Decision

Use DynamoDB with a single-table design: device profiles and diagnostic events
share one partition per device (`PK = DEVICE#<id>`), a sparse GSI1 answers "list
devices", and a TTL attribute expires events. On-demand (PAY_PER_REQUEST)
billing is used. Idempotency is a conditional `PutItem` on `event_id` with a
stored payload hash.

## Alternatives

- **Relational (RDS/Aurora Serverless)**: richer queries but higher idle cost and
  more operational surface than the access patterns need. Rejected.
- **Multiple DynamoDB tables**: more items to manage and cross-table reads; the
  single-table design covers every access pattern. Rejected.

## Consequences

- Access patterns are fixed by the key design (documented in
  [data-model.md](../data-model.md)); new patterns may need a new GSI.
- Exactly-once storage via conditional writes; duplicates and conflicts are
  explicit.
- Point-in-time recovery is off by default as a cost trade-off.
