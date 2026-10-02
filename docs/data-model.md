# Data model

> Language: English · [Português (Brasil)](data-model.pt-BR.md)

Two stores: the cloud single-table DynamoDB design and the local SQLite
database.

## DynamoDB single table

One table (`${StackName}-diagnostics`), on-demand billing, a sparse GSI1, and a
TTL attribute. Device profiles and diagnostic events share one partition per
device.

Keys and attributes:

- `PK` (S): `DEVICE#<device_id>` for both entities.
- `SK` (S): `PROFILE` for the device profile; `DIAG#<event_id>` for an event.
  Because `event_id` is a UUIDv7 (time-ordered), the sort key is naturally
  chronological, so "newest first" is a reverse `Query`.
- `GSI1PK` / `GSI1SK` (S): only profiles carry these (`GSI1PK = DEVICE`,
  `GSI1SK = DEVICE#<device_id>`), making GSI1 sparse so "list devices" scans
  profiles only.
- `expires_at` (N, epoch seconds): TTL on diagnostic events (default 30 days).

Access patterns:

| ID | Question | Operation |
|---|---|---|
| AP1 | register / update a device | `UpdateItem` on `(PK, PROFILE)`, idempotent |
| AP2 | read one device | `GetItem` on `(PK, PROFILE)` |
| AP3 | list devices | `Query` GSI1 `GSI1PK = DEVICE`, paginated |
| AP4 | ingest an event | conditional `PutItem` (`attribute_not_exists(PK)`) |
| AP5 | recent diagnostics | `Query` `PK = DEVICE#id AND begins_with(SK, 'DIAG#')`, reverse |
| AP6 | update latest status | `UpdateItem` guarded by `latest_event_id < :eid` |
| AP6b | advance `last_seen_at` | `UpdateItem` with `attribute_exists(PK)` |

Idempotency: the conditional put stores a `payload_sha256`. A reused `event_id`
with the same payload is a `duplicate` (one item stored); a reused id with a
different payload is `EVENT_ID_CONFLICT` (rejected). On-demand billing avoids
capacity planning for a spiky, low-volume workload; the TTL expires old events
for free; point-in-time recovery is off by default as a documented cost
trade-off.

Stored profile fields answered by AP2/AP3 include `device_id`, `device_name`,
`os`, `hardware`, `agent_version`, `registered_at`, `updated_at`,
`last_seen_at`, and the `latest_*` summary. The public API strips internal keys
(`PK`, `SK`, `GSI1*`, `entity`, `payload_sha256`, `payload`) and converts
DynamoDB `Decimal` numbers back to `int`.

## Local SQLite

WAL mode, foreign keys on, migrations keyed by `PRAGMA user_version`, and
`PRAGMA application_id` to distinguish live from demo databases (so demo mode
never deletes a file it did not create).

- `devices` — one local identity (`is_local = 1`, enforced by a partial unique
  index), overrides stored with `is_local = 0`; also holds the registration
  fingerprint used to skip unchanged re-registration.
- `diagnostic_runs` — one row per run with the full `result_json`, indexed by
  `(device_id, started_at DESC)`.
- `diagnostic_results` — flattened checks/alerts/metrics for querying, with the
  rich detail in `details_json`.
- `sync_queue` — one row per event: `state`, `attempt_count`, `next_attempt_at`,
  `claimed_at`, the frozen `payload_json`, and timestamps. `run_id` is UNIQUE so
  one run maps to one event.
- `sync_attempts` — an append-only audit of every delivery attempt with
  `outcome`, `http_status`, `error_code` and timing.

The write path (`LocalStore.save_run`) inserts the run, its results and the
queue event inside one `BEGIN IMMEDIATE` transaction, so a persisted run that
should sync always has a queue event and vice versa.
