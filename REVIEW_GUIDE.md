# Review & Study Guide — Local-to-Cloud Diagnostic Gateway

> Documentation language: English (this file) · [Português (Brasil)](REVIEW_GUIDE.pt-BR.md)

This is a technical review-and-study guide for the finished project. It is
documentation only: no production code was changed, no feature was added, no
test was created, nothing was deployed. The code and docs on disk are the single
source of truth. Where documentation and implementation disagree, the divergence
is recorded explicitly (see the final section, *Source-of-Truth Verification*).

How to use it: read top to bottom once to build a mental model, then use
sections 16–20 as an active study/interview track. File paths are given so you
can jump straight to the code behind every claim.

---

## 1. Project Overview

**Problem solved.** Diagnosing a machine that is itself having connectivity
problems is awkward: a cloud-only agent stops being useful exactly when the
network degrades. This project runs all diagnostics locally and treats the cloud
as an optional, best-effort archive. (`README.md`, `docs/decisions/ADR-001-local-first.md`.)

**System objective.** A Windows-first Python agent collects hardware, OS,
storage and network telemetry, evaluates deterministic health rules locally,
persists every run in SQLite, and keeps working with no internet. A minimized,
scrubbed subset of each run is queued locally and synchronized to an AWS
serverless backend (HTTP API Gateway → Lambda → single-table DynamoDB) with a
bounded, backoff-driven retry policy and exactly-once (idempotent) ingestion.

**Local-first principle.** Diagnostics, health evaluation and persistence run
entirely on the host with no network dependency. Every local command works
offline. Sync is a separate, optional step that reads an already-persisted
queue; its failures never alter the diagnostic result. Persist + enqueue happen
in one local transaction *before* any sync. (`ADR-001`, `docs/architecture.md`.)

**What works locally (no cloud, no network).**
- `diagnostic-agent hardware` — read-only hardware inventory.
- `diagnostic-agent network` — collection + classification with evidence/causes.
- `diagnostic-agent health` — full pipeline, no DB write.
- `diagnostic-agent scan` — full pipeline, persists the run (and enqueues when sync is enabled).
- `diagnostic-agent status` / `queue list` / `queue stats` — read-only inspection.
- `diagnostic-agent demo [--all | --scenario NAME]` — six deterministic scenarios over simulated inputs.
- `diagnostic-agent run [--iterations N]` — scan+sync loop on the telemetry interval.

**What belongs to the AWS layer.** The optional backend: an HTTP API Gateway, four
Lambda functions (`health`, `device`, `telemetry`, `diagnostic`), a single
DynamoDB table with a GSI and TTL, two SSM SecureString API keys, CloudWatch
logs + EMF metrics, and per-function IAM roles. All declared in
`infrastructure/template.yaml` (AWS SAM).

**Out of current scope (confirmed; see §15).** Not deployed to AWS; no Windows
Service / scheduled-task installer; no remote command execution; no web
dashboard; no SNS/CloudWatch alarms; no Linux/macOS collectors; no per-device
credentials or mTLS; disabled-sync runs are not back-filled.

---

## 2. End-to-End Architecture

The canonical flow (from `diagrams/architecture.mmd` / `README.md`):

```
Windows Agent → Collectors → Diagnostic Engine → SQLite → Offline Queue
   → Sync Service → HTTP(S) ApiClient → API Gateway → Lambda → DynamoDB
```

Cross-cutting AWS services: **CloudWatch** (logs + EMF metrics), **SSM Parameter
Store** (two SecureString keys), **IAM** (one role per function), **SAM** (the
template that declares all of it).

Per component — responsibility, input, output, dependencies, communication, file(s):

| Component | Responsibility | Input | Output | Depends on | Talks to | File(s) |
|---|---|---|---|---|---|---|
| CLI / orchestration | Parse args, map exit codes, wire the pipeline | argv, `.env`, env vars | process exit code, report | `argparse`, settings | commands → pipeline/sync | `src/agent/main.py`, `src/agent/commands.py` |
| Collectors | Read one domain each (CPU/mem/storage/system/GPU/disk/network) | OS/psutil/PowerShell | typed dataclasses (`CpuInfo`, …) | `psutil`, platform module | pipeline via `run_collector` | `src/agent/collectors/*`, `src/agent/collectors/base.py` |
| platform_support | Read-only Windows CIM via PowerShell | subprocess output | parsed JSON facts | `subprocess`, PowerShell | collectors | `src/agent/platform_support/*` |
| Diagnostic engine | Collect → diagnose → evaluate into a `DiagnosticResult` | collector results, probes | `DiagnosticResult` (checks/alerts/metrics/facts/status) | collectors, probes, rules, thresholds | pipeline/commands | `src/agent/pipeline.py`, `src/agent/diagnostics/engine.py`, `diagnostics/network_diagnostics.py`, `diagnostics/rules.py`, `diagnostics/health.py`, `diagnostics/probes.py` |
| SQLite (LocalStore) | Durable, transactional persistence of runs/results/queue | `DiagnosticResult` | rows in `diagnostic_runs`, `diagnostic_results`, `sync_queue` | `sqlite3`, WAL | pipeline, sync service | `src/agent/storage/local_db.py` |
| Offline queue | Owns every queue state transition | queue rows, clock | state changes, `sync_attempts` rows | `sqlite3`, backoff policy | sync service | `src/agent/storage/queue.py`, `src/agent/sync/retry.py` |
| Sync service | One bounded sync cycle: register, batch, deliver, transition | queue, settings, device id | `SyncReport` | queue, ApiClient, serializer, shared schema | ApiClient → cloud | `src/agent/sync/service.py` |
| Serializer | Whitelist + IP-scrub the uploaded payload | `DiagnosticResult` | minimized event / registration dict | `ipaddress`, shared models | sync service | `src/agent/sync/serializer.py` |
| ApiClient / transport | HTTP + ordered response classification; no redirects | event/registration dict | typed results or typed errors | `urllib`, `ssl` | API Gateway | `src/agent/sync/client.py` |
| API Gateway (HTTP API v2) | Public HTTPS entry; route + throttle + access log | HTTPS request | Lambda proxy event | — | Lambda | `infrastructure/template.yaml` (`HttpApi`) |
| Lambda × 4 | Stateless per-route compute | API Gateway v2 event | proxy response | shared schema, repository, auth, http | DynamoDB, SSM, CloudWatch | `src/cloud/handlers/{health,device,telemetry,diagnostic}.py`, `src/cloud/http.py` |
| Auth | Bearer key verification, two scopes | `Authorization` header | `None` / `Unauthorized` / `Forbidden` | SSM, `hmac` | SSM | `src/cloud/auth.py` |
| Repository | Single-table DynamoDB access patterns | handler calls | DynamoDB items / outcomes | `boto3` | DynamoDB | `src/cloud/repository.py`, `src/cloud/cursor.py` |
| DynamoDB | Durable, idempotent store (profiles + events) | PutItem/GetItem/Query/UpdateItem | items, TTL expiry | — | repository | `infrastructure/template.yaml` (`DiagnosticsTable`) |
| CloudWatch | Logs + EMF custom metrics | stdout JSON / EMF lines | metrics, log groups | — | all Lambdas | `src/cloud/metrics.py`, `src/shared/utils/json_logging.py`, template log groups |
| SSM Parameter Store | Holds the two SecureString keys | `GetParameters` | decrypted key values | KMS `alias/aws/ssm` | auth | template params + `DeviceRole`/`TelemetryRole`/`DiagnosticRole` |
| IAM | Least-privilege role per function | — | scoped permissions | — | AWS services | `infrastructure/template.yaml` roles |
| SAM | Declares the whole backend as code | parameters | CloudFormation stack | CloudFormation | all AWS resources | `infrastructure/template.yaml`, `infrastructure/samconfig.toml` |

Communication facts worth memorizing: the agent speaks **HTTPS JSON with a
Bearer token and refuses redirects**; the shared validator in
`src/shared/schemas` is the **contract both sides use** (the agent pre-checks
every event with the same code the cloud enforces); the Lambda bundle is
**stdlib + boto3 only** (an import-boundary test keeps `psutil`-dependent agent
code out of `cloud`).

---

## 3. Repository Map

Only architecturally important files. For each: path · responsibility · why it
exists · who calls it · what it calls · technical concepts.

**Agent entry & orchestration**
- `src/agent/main.py` — argparse wiring + exit-code policy (0 ok, 1 error, 2 usage/config, 3 sync incomplete, 130 interrupt). Exists to keep `main` thin. Called by the `diagnostic-agent` console script / `python -m agent`. Calls `commands.*`. Concepts: CLI design, exit codes.
- `src/agent/commands.py` — one handler per subcommand; opens/closes the DB, resolves identity, runs pipeline/sync. Exists so each command is unit-testable. Called by `main`. Calls `pipeline`, `storage`, `sync` (lazily). Concepts: resource lifetimes, exit precedence (1 > 3 > 0), lazy imports for the local-first boundary.
- `src/agent/pipeline.py` — `DiagnosticPipeline.run`: collect → diagnose → evaluate → (persist + enqueue). Exists to make providers injectable (demo/tests swap simulated ones). Called by `commands`, `demo`. Calls collectors, `NetworkDiagnostics`, `evaluate_result`, `LocalStore.save_run`. Concepts: dependency injection, Protocols, invariant checks via explicit `ValueError`.
- `src/agent/identity.py` — `resolve_device_id`: UUIDv4 identity with a single `is_local=1` row, or a `DEVICE_ID` override (`is_local=0`). Called by `commands`, sync. Calls `sqlite3`. Concepts: stable identity decoupled from IP/serials, partial unique index.

**Diagnostics**
- `src/agent/diagnostics/engine.py` — `collect_all` / `diagnose` / `evaluate_result`; builds metrics (drops `None`). Read-only; never imports `sync`. Concepts: separation of collection vs evaluation.
- `src/agent/diagnostics/network_diagnostics.py` — gateway/internet/DNS probing + first-match classification (UNKNOWN/OFFLINE/UNSTABLE/DEGRADED/HEALTHY). Key privacy rule: **evidence refers to interfaces by count only, never by name**. Concepts: network classification, TCP-probe-failure-rate as "packet loss".
- `src/agent/diagnostics/probes.py`, `rules.py`, `health.py`, `facts.py` — probe primitives, deterministic threshold rules, health aggregation, facts dictionary.

**Collectors / platform**
- `src/agent/collectors/base.py` — `run_collector`: the isolation boundary; any collector failure becomes a `CollectorResult` status (OK/PARTIAL/FAILED/UNAVAILABLE), never a crash. Concepts: fault isolation, structured error text (no paths beyond mountpoints).
- `src/agent/collectors/{cpu,memory,storage,system,network,hardware}.py` — per-domain readers.
- `src/agent/platform_support/{windows,powershell,base}.py` — read-only CIM queries, `PlatformQueryError`/`PlatformUnavailableError`.

**Storage & queue**
- `src/agent/storage/local_db.py` — `connect` (writable vs `mode=ro`), migrations by `PRAGMA user_version`, `PRAGMA application_id` marker (live vs demo), `LocalStore.save_run` (atomic `BEGIN IMMEDIATE`). Concepts: WAL, migrations, transactions, the run/queue invariant.
- `src/agent/storage/queue.py` — `SyncQueue`: the only writer of `state`; claim/recover/mark_synced/mark_failed/mark_dead/release/requeue. Concepts: state machine, lease recovery, backoff application.

**Sync**
- `src/agent/sync/service.py` — `SyncService.run_cycle`: recover stale → register (fingerprinted) → claim due → byte-pack batches → deliver → transition. Concepts: batching, re-registration on 409, abort reasons.
- `src/agent/sync/client.py` — transport Protocol + `UrllibTransport` (no redirects) + `ApiClient` with the ordered seven-row classification. Concepts: delivered vs not-delivered error boundary, HTTP status mapping.
- `src/agent/sync/serializer.py` — whitelist builder + `scrub_ips`. Concepts: data minimization, `ipaddress`-validated redaction.
- `src/agent/sync/retry.py` — `BackoffPolicy.delay`: `min(max, base·2^(n-1))·uniform(0.5,1.0)`. Concepts: exponential backoff + jitter.

**Config / logging**
- `src/agent/config/settings.py` — `Settings`, `Thresholds`, `SyncSettings`, `Secret`, `load_settings`. `SyncSettings` lives here on purpose (local-first import boundary). Concepts: precedence env > `.env` > default, validation collecting all errors, secret wrapper.
- `src/agent/logging/logger.py`, `src/shared/utils/json_logging.py` — JSON logging + redaction filter.

**Cloud**
- `src/cloud/http.py` — `Request.from_event` (API Gateway v2), `@api_handler` (scope enforcement + exception→envelope mapping), `parse_json_body`. Concepts: proxy integration, error table.
- `src/cloud/auth.py` — `ApiKeyProvider`: SSM-cached two-scope keys, byte-safe bearer parsing (M2). Concepts: constant-time compare, caching with stale-tolerance.
- `src/cloud/errors.py` — `ApiError` hierarchy → status/code/headers (401 `WWW-Authenticate`, 503 `Retry-After`).
- `src/cloud/repository.py` — single-table access patterns AP1–AP6b, idempotent conditional put, `to_public` stripping internal keys, `Decimal`→`int`.
- `src/cloud/cursor.py` — opaque base64url cursors, strictly validated and device-bound.
- `src/cloud/metrics.py` — EMF line builder, eight metric names, `[["Service","Function"]]` dimension.
- `src/cloud/handlers/{health,device,telemetry,diagnostic}.py` — the four Lambda entry points; `_support.py` shared plumbing.

**Shared**
- `src/shared/schemas/{common,device,telemetry}.py` — the API contract validators and size constants (`MAX_REQUEST_BYTES`, `MAX_EVENT_BYTES`, `AGENT_VERSION_PATTERN`, `DEVICE_ID_PATTERN`, `MAX_CLOCK_SKEW_SECONDS`).
- `src/shared/models/{device,diagnostic}.py` — frozen dataclasses + enums (`HealthStatus`, `NetworkStatus`, `CheckStatus`, `Severity`, `RunSource`).
- `src/shared/utils/{ids,timeutil,json_logging}.py` — UUIDv7, ISO time, JSON logging.

**Infra / scripts / docs**
- `infrastructure/template.yaml` + `samconfig.toml` — the SAM backend.
- `scripts/deploy.*`, `teardown.*`, `validate-infra.*`, `local_cloud.py` — manual deploy/validate helpers (never auto-run).
- `docs/*` + `docs/decisions/ADR-00{1..7}` + `diagrams/*.mmd` — see §4.

---

## 4. Documentation History

- `README.md` / `README.pt-BR.md` — the entry point: problem statement, architecture Mermaid, tech stack with versions, features, install, local execution, deployment note (nothing deploys from the repo), security/cost/privacy summaries, limitations, the bilingual documentation convention.
- `docs/architecture.md` — components (Python + AWS tables), the data-flow diagram, identity, the SQLite schema, the sync state machine, the **failure matrix** (the single most useful page), and the deviations from the original spec. Also the TCP-probe-failure-rate note explaining what "packet loss" means here.
- `docs/api.md` — the `/v1` + `/health` contract per endpoint (see §12).
- `docs/data-model.md` — the DynamoDB single-table design (keys, GSI1, TTL, access patterns AP1–AP6b) and the SQLite tables.
- `docs/security.md` — transport, two-scope auth, the IAM matrix, secrets, input validation, data minimization, `sourceIp` retention, trust boundaries.
- `docs/threat-model.md` — nine threats, each with impact/mitigation/residual risk (stolen key, replay, MITM/redirect, log leakage, injection, DoS/cost, cross-function escalation, read-API exposure, tampered cursor).
- `docs/cost.md` — service cost model, drivers, the EMF custom-metric billing note (~10–12 billable metrics in active months), minimization, teardown.
- `docs/observability.md` — log fields, the eight EMF metrics, and the agent-side offline-vs-delivered-but-failed split.
- `docs/troubleshooting.md` — operator and deploy-time first checks.
- `docs/engineering-report.md` — architecture/components/data-flow/security/reliability/AWS/cost/testing summary, the final verification run figures, and the "What the developer must understand" list.
- `diagrams/architecture.mmd`, `data-flow.mmd`, `sync-state-machine.mmd` — Mermaid sources embedded in the docs and checked by a quality test.

**ADRs** (problem · decision · relevant alternatives · reason · technical impact):

- **ADR-001 Local-first.** Problem: a cloud-dependent agent fails exactly when the network degrades, and upload-before-persist risks data loss. Decision: diagnostics/evaluation/persistence are fully local; sync is a separate optional step reading an already-persisted queue. Alternatives: cloud-first (loses data in outages), cloud-only (no offline). Reason: usefulness on isolated machines; no data loss. Impact: requires a durable local queue + state machine (ADR-005); disabled-sync runs are not back-filled (a deliberate minimization choice).
- **ADR-002 Serverless backend.** Problem: spiky, tiny telemetry that must cost ~nothing when idle, run by one person. Decision: HTTP API Gateway + four Lambdas + DynamoDB + SSM + CloudWatch. Alternatives: containers/EC2 (always-on cost/patching), one monolithic Lambda (one over-broad role). Reason: near-zero idle cost, per-function least privilege. Impact: AWS-specific; cold starts accepted for an hourly async path.
- **ADR-003 DynamoDB.** Problem: serverless, pay-per-use, durable store for a few key-based access patterns with auto-expiry. Decision: single-table design (`PK=DEVICE#<id>`, sparse GSI1, TTL), on-demand billing, conditional-put idempotency on `event_id` + payload hash. Alternatives: RDS/Aurora (idle cost, more surface), multiple tables (cross-table reads). Reason: fits the fixed access patterns cheaply. Impact: new access patterns may need a new GSI; PITR off by default (cost trade-off).
- **ADR-004 SQLite local storage.** Problem: durable, transactional, zero-setup local storage. Decision: stdlib `sqlite3` in WAL, FKs on, `user_version` migrations, `application_id` live/demo marker, one `BEGIN IMMEDIATE` transaction per run. Alternatives: flat files (no transactions/locking), embedded server (install/run a server on an edge box). Reason: no dependency, atomic run/queue invariant. Impact: single-writer concurrency; a locked DB is a clean exit 1.
- **ADR-005 Offline sync queue.** Problem: results must survive long outages and reach the cloud exactly once, without a busy loop. Decision: explicit `sync_queue` state machine with per-attempt audit; delivered-but-failed back off and dead-letter at `RETRY_LIMIT`; a **provably-not-delivered (OFFLINE) attempt does not consume the retry budget**. Alternatives: count offline cycles against the limit (would dead-letter during normal outages), in-process retry loop (hammers the network), external broker (adds a dependency). Reason: offline is the product's normal condition. Impact: a misconfigured non-resolving URL keeps events PENDING forever (visible via `status`); crash recovery reclaims stale `SYNCING` leases.
- **ADR-006 IaC with SAM.** Problem: reproducible, reviewable infra, deployable with scripts and validatable offline (no SAM CLI on the dev box). Decision: AWS SAM, validated with `cfn-lint`; one explicit IAM role per function. Alternatives: CDK (Node toolchain), Terraform (second language + state backend), click-ops (not reproducible). Reason: one-to-one mapping to the architecture, CloudFormation holds state. Impact: IAM verbosity accepted for explicit least privilege; `sam validate` deferred.
- **ADR-007 API authentication.** Problem: simple auth that separates write/read, keeps secrets out of code/logs, and is safe against hostile input. Decision: Bearer key with two scopes (`ingest`/`read`) in SSM SecureStrings, cached 5 min, stale-tolerant; byte-safe parsing + `hmac.compare_digest`; non-ASCII token → 401 not 500; scope enforced in `@api_handler`. Alternatives: Lambda authorizer/Cognito/SigV4 (heavier), single key (no scope separation), per-device creds (more key management). Reason: minimal operation for v1. Impact: a leaked ingest key can spoof device IDs until rotated; `sourceIp` is the attribution evidence.

---

## 5. Local Agent Deep Dive

**`main.py`.** Builds the argparse tree (one subparser per command, with
`--json`/`--sync`/`--force`/`--iterations` where relevant), sets `func` on the
namespace, then calls it inside a top-level guard that maps `KeyboardInterrupt`
→ 130 and any other exception → logged error + exit 1. No command means print
help + exit 2.

**`commands.py`.** Thin orchestration. Each handler loads settings
(`_load`, returning `None`/exit 2 on `ConfigError`), opens the DB when needed,
resolves identity, and runs work. Important behaviors to internalize:
- Read-only commands (`hardware`, `network`, `health`, `status`, `queue list`/`stats`) never create or migrate the DB and never import `sync`.
- `scan` runs the pipeline, persists, prints the report; `--sync` runs one cycle after. Exit precedence is **1 > 3 > 0** (`_worse_exit`): a storage error outranks an incomplete sync.
- A `StorageError` during `scan` still re-runs the pipeline *without a store* so the operator sees current state, logs `event=storage_error`, and exits 1.
- `run` loops scan+sync on `telemetry_interval_seconds`, sleeping interruptibly (≤1s slices) so Ctrl+C is responsive; with `--iterations N` it applies the same 1 > 3 > 0 precedence across iterations.
- `queue requeue` is the only queue-writing maintenance command (dead → PENDING).

**`pipeline.py`.** `DiagnosticPipeline` holds injected `CollectorSet`, `Prober`,
`HealthEvaluator`, `Clock` — so demo/tests substitute simulated providers with
no branching in production code. `run(device_id, store, source, *, enqueue)`:
- Guards the invariant **`device_id is None` with a `store` → `ValueError`** (a run without identity can never be persisted) using an explicit error, not an `assert` (`-O` would strip it).
- `_collect()` runs every collector through `run_collector` (isolation).
- Runs `NetworkDiagnostics`, then `evaluate_result` → a `DiagnosticResult`.
- When `store` is given, `store.save_run(result, enqueue_event=enqueue)` persists and (optionally) enqueues in one transaction.

**`collectors/`.** `base.run_collector(name, fn)` is the single try/except
boundary: `PartialCollection` → PARTIAL (keeps partial data + item errors);
`PlatformUnavailableError` → UNAVAILABLE; `PlatformQueryError`/`OSError`/
`psutil.Error` → FAILED; any other exception → FAILED (last-resort). It never
raises; one broken collector never aborts the run. Error strings carry only the
error class/message.

**`diagnostics/`.** `engine.collect_all` + `diagnose` + `evaluate_result` build
checks/alerts/metrics and the overall `HealthStatus`/`NetworkStatus`.
`rules.py` is a list of pure `(DiagnosticInput, Thresholds) → RuleOutcome`
functions with unique check names and a fixed order; a missing input yields a
SKIPPED check. `network_diagnostics.py` classifies connectivity first-match
(UNKNOWN → OFFLINE → UNSTABLE → DEGRADED → HEALTHY) and refers to interfaces by
count. Metrics with a `None` value are omitted (never null/NaN).

**`storage/local_db.py`.** `connect` is the one entry point: writable
connections create the parent dir, enable WAL + foreign keys, and migrate by
`PRAGMA user_version`; read-only connections open `mode=ro`, never migrate, and
raise `SchemaOutdatedError` on an old version. `LocalStore.save_run` writes the
run, its results and (optionally) the queue event in one `BEGIN IMMEDIATE`
transaction, freezing the queue payload JSON so retries send byte-identical
bytes.

**`storage/queue.py`.** `SyncQueue` owns every `state` write (see §6).

**`sync/`.** `service.SyncService.run_cycle` orchestrates one cycle;
`client.ApiClient` classifies HTTP outcomes; `serializer` minimizes/scrubs;
`retry.BackoffPolicy` computes jittered delays (see §6 and §7).

**`demo.py`.** `diagnostic-agent demo` runs the *real* pipeline/rules/
serializer/report over simulated collector + probe providers, so output is
deterministic and touches neither the real network, the live DB, PowerShell nor
psutil (a test patches `subprocess`, `socket`, and `psutil` to raise). Six
scenarios: HEALTHY, DEGRADED_NETWORK, LOW_DISK, HIGH_MEMORY, DNS_FAILURE,
OFFLINE_MODE. `OFFLINE_MODE` additionally runs one sync cycle against an
unreachable `demo.invalid` endpoint so the queue goes PENDING with one OFFLINE
attempt per event, budget untouched. See §8 for the deletion guard.

### The main pipeline: collect → diagnose → persist → enqueue

Grounded in `pipeline.py` + `local_db.py`:

1. **collect.** `_collect()` builds a `Collected` by running each collector via
   `run_collector`. Errors are captured as a status; the run always proceeds.
2. **diagnose.** `NetworkDiagnostics(prober, settings).run(collected.network)`
   probes gateway/internet/DNS and classifies; `evaluate_result` runs the health
   rules into checks/alerts/metrics and derives the overall status. Probe/rule
   failures degrade to SKIPPED/UNKNOWN, not crashes.
3. **persist.** If a `store` is present, `save_run` inserts one
   `diagnostic_runs` row + the flattened `diagnostic_results` rows inside one
   transaction. A `sqlite3.Error` becomes a `StorageError` (rolled back; caller
   exits 1 but still prints the report).
4. **enqueue.** Within the *same* transaction, when `enqueue=settings.sync_enabled`
   is true, one `sync_queue` row is inserted (state PENDING, `attempt_count=0`,
   a frozen `payload_json`). This guarantees the invariant: a persisted run that
   should sync always has a queue event, and every queued event has its run.

Error handling summary: collector errors → section status, run continues;
missing rule input → SKIPPED; storage error → `StorageError`, rollback, exit 1,
report still printed; the pipeline itself never performs network I/O.

---

## 6. SQLite and Offline Queue

**Tables** (`_SCHEMA_V1` in `storage/local_db.py`):
- `devices(device_id PK, device_name, hostname, is_local CHECK(0,1), created_at, registration_fingerprint, registered_at)` with a **partial unique index** `idx_devices_single_local ON devices(is_local) WHERE is_local = 1` (at most one local identity).
- `diagnostic_runs(run_id PK, device_id FK, source CHECK('live','demo'), scenario, started_at, finished_at, status, network_status, result_json)`; index `(device_id, started_at DESC)`.
- `diagnostic_results(id PK AUTOINCREMENT, run_id FK ON DELETE CASCADE, result_type CHECK('check','alert','metric'), name, status, value, unit, subject, details_json)`.
- `sync_queue(event_id PK, run_id UNIQUE FK, device_id FK, event_type DEFAULT 'diagnostic_run', payload_json, state CHECK(PENDING,SYNCING,SYNCED,FAILED,DEAD_LETTER), attempt_count, next_attempt_at, claimed_at, last_error, created_at, updated_at, synced_at)`; index `(device_id, state, next_attempt_at)`.
- `sync_attempts(id PK AUTOINCREMENT, event_id FK, attempted_at, outcome CHECK(ACCEPTED,DUPLICATE,REJECTED,TRANSIENT_ERROR,OFFLINE,AUTH_ERROR,CONFIG_ERROR,INTERRUPTED), http_status, error_code, error_message, duration_ms, request_id)`; index on `event_id`.

**Migrations.** Keyed by `PRAGMA user_version` (currently `SCHEMA_VERSION = 1`).
On a version-0 writable DB, `_migrate` runs the schema script, sets
`PRAGMA application_id` to `DEMO_DB_APPLICATION_ID` (demo) or
`LIVE_DB_APPLICATION_ID` (live), then `user_version = 1`.

**WAL.** `PRAGMA journal_mode = WAL` plus `busy_timeout = 5000ms` on writable
connections, so readers don't block the single writer and transient locks wait.

**Transactions.** `LocalStore._transaction` wraps work in `BEGIN IMMEDIATE` with
rollback on any `BaseException`. Queue claims (`claim_due`) also use
`BEGIN IMMEDIATE` so only rows actually updated to SYNCING are returned
(no double-send).

**Queue states & transitions** (`storage/queue.py`): `PENDING → SYNCING →
(SYNCED | FAILED | DEAD_LETTER)`. `FAILED` becomes due again when
`next_attempt_at <= now`. `release` returns a claimed row to PENDING (if
`attempt_count == 0`) or FAILED (otherwise) **without counting an attempt**.
`requeue_dead` moves DEAD_LETTER → PENDING with `attempt_count = 0`.

**Retry / backoff / jitter.** `BackoffPolicy.delay(attempt)` =
`min(max_s, base_s · 2^(attempt-1)) · uniform(0.5, 1.0)` with an injected RNG
(deterministic in tests). There is **no in-process retry loop**: a FAILED event
just waits for a later cycle. `mark_failed` dead-letters at
`attempt >= retry_limit`, else sets FAILED with a backoff `next_attempt_at`.

**Stale recovery.** `recover_stale` finds rows stuck in SYNCING with
`claimed_at` older than `SYNC_LEASE_SECONDS = 300`, records an `INTERRUPTED`
attempt (counted, because the request may have been delivered) and moves them to
FAILED with `attempt_count + 1`.

**Dead-letter.** Reached by permanent rejection (`mark_dead`) or by exhausting
`retry_limit` (`mark_failed`). Recoverable only via `queue requeue`.

**Idempotency / event_id.** `event_id` is a UUIDv7 (time-ordered) generated at
enqueue; `run_id` is UNIQUE so one run maps to exactly one event; the frozen
`payload_json` means every retry sends byte-identical content, which the cloud
treats as the same item (see §11).

**State-machine (textual), matching `queue.py`:**

```
            enqueue during scan
                 │
                 ▼
             [PENDING] ──claim_due──► [SYNCING] ──accepted/duplicate──► [SYNCED] ─► done
                 ▲                        │
   release(attempt_count==0)              ├── transient err, attempt<limit ─► [FAILED]
                 │                        │                                     │
                 │                        ├── rejected OR attempt>=limit ─► [DEAD_LETTER]
                 │                        │                                     │
                 │                        └── release(offline/auth/config):     │
                 │             attempt_count==0 → PENDING, else → FAILED         │
                 │                                                               │
             [FAILED] ──claim_due (next_attempt_at<=now)──► [SYNCING]            │
                                                                                 │
             [DEAD_LETTER] ──queue requeue──► [PENDING] ◄───────────────────────┘

   Stale lease: [SYNCING] (claimed_at older than SYNC_LEASE_SECONDS)
                → INTERRUPTED attempt (counted) → [FAILED]
   Note: OFFLINE attempts are recorded in sync_attempts but never consume RETRY_LIMIT.
```

---

## 7. Synchronization Flow

How an event leaves SQLite and reaches the backend (`sync/service.py`,
`sync/client.py`, `storage/queue.py`):

1. **Guard & recover.** `run_cycle` returns `disabled` when sync is off/no key.
   It records `other_device_pending`, runs `recover_stale`, and returns early if
   nothing is due.
2. **Register (fingerprinted).** `_ensure_registration` builds the registration
   payload from the newest run's facts, hashes it (SHA-256) and skips the call
   if unchanged. Registration failures route through `_handle_registration_failure`.
3. **Claim.** `claim_due` atomically moves up to `batch_size` due rows to
   SYNCING (ordered by `next_attempt_at`, then `created_at`), excluding events
   already handled this cycle.
4. **Byte-pack.** `_pack` greedily adds events while the serialized envelope
   stays `<= MAX_REQUEST_BYTES` (256 KiB) and `len <= batch_size`; overflow is
   released (uncounted) for a later batch. Up to `max_batches` batches per cycle.
5. **Deliver & classify.** `ApiClient.send_telemetry` runs the ordered
   seven-row classification; the queue state machine applies the result.

**HTTP classification** (`client.py`, first match wins):
- **Row 1 — not delivered / delivery uncertain.** `ConnectivityError` →
  `OfflineError`; `DeliveryUncertainError` (timeout, reset after send, TLS, other
  OSError after the request left) → `TransientSyncError`.
- **Row 2 — redirect (3xx).** Refused by `_NoRedirect` → `ConfigurationError`
  (the ingest key is never copied to another host).
- **Row 3 — 401/403.** `AuthError`.
- **Row 4 — 429 / 500 / 502 / 503 / 504.** `TransientSyncError` (carries status).
- **Row 5 — malformed 2xx body.** `MalformedResponseError` (a `TransientSyncError`
  subclass; retry is safe).
- **Row 6 — enveloped 4xx.** 409 `DEVICE_NOT_REGISTERED` →
  `DeviceNotRegisteredError`; 413 multi-event → `PayloadTooLargeError`; 413 single
  event → `PermanentSyncError`; other enveloped 4xx → `PermanentSyncError`.
- **Row 7 — anything else.** `ConfigurationError`.

**Service response to each outcome** (`service.py`):
- **offline** → release the batch (OFFLINE attempt), abort cycle, `aborted="offline"`.
- **401/403** → release (AUTH_ERROR), `aborted="auth"`.
- **config/redirect/unexpected** → release (CONFIG_ERROR), `aborted="config"`.
- **413 (multi)** → `_split_413`: release, resend one event per request.
- **permanent (enveloped 4xx / single 413)** → `_dead` each event → DEAD_LETTER.
- **409** → `_handle_409`: re-register once, then re-deliver; if re-registration itself fails, route per its own branches.
- **malformed / transient (incl. 5xx/429/delivery-uncertain)** → `_fail` each event (counts an attempt; FAILED with backoff or DEAD_LETTER at the limit).
- **200 well-formed** → `_apply_items`: `accepted`/`duplicate` → `mark_synced`; `CLOCK_SKEW` → `_fail` (transient, logged); any other per-item code → `_dead`.

**Re-registration.** On 409 the service registers again (if `allow_reregister`),
stores the new fingerprint, and re-delivers the same batch; the inner delivery
disables further re-registration to avoid loops.

**The retry-budget rule — verified against the code.** A **provably-not-delivered
(offline) attempt does not consume the retry budget**: `ConnectivityError →
OfflineError` leads to `SyncQueue.release`, which does not increment
`attempt_count` and leaves `next_attempt_at` unchanged. The same uncounted
release applies to 401/403 and config/redirect aborts. This matches ADR-005,
`docs/observability.md` and the failure matrix, and is proven by
`tests/integration/test_offline.py` (after an offline scan+sync the event is
still PENDING, `attempt_count == 0`, `next_attempt_at` unchanged, with one
`OFFLINE` attempt row).

**Important nuance (not a divergence, but a common misreading).** "Network
failure" is split in two. Only the *provably not delivered* case is OFFLINE and
uncounted. A **delivery-uncertain** failure (connect succeeded then timeout/reset,
TLS error, or any OSError raised after the request was sent) is classified as
`DeliveryUncertainError → TransientSyncError` and **does** consume the budget
(it may have been delivered, so it must back off and can dead-letter). So the
precise rule is: *offline/not-delivered and auth/config aborts don't consume the
budget; delivered-or-maybe-delivered failures do.* `docs/observability.md`
("Agent-side sync-failure split") states exactly this.

---

## 8. Security Review

Primary controls: HTTPS with certificate verification and **no redirects**;
two-scope Bearer auth with SSM-stored keys; one least-privilege IAM role per
function (no wildcards); strict shared-schema validation on both sides; data
minimization + IP scrubbing before upload; `Secret` wrapper + log redaction.

### (a) `demo.py` — refusing to delete an arbitrary SQLite file (M1)

`DEMO_DATABASE_PATH` is user-configurable, so a naive "delete demo.db at start
of each run" could wipe a file the agent did not create. The guard
(`DemoRunner.prepare_database`):
1. Refuses (exit 2) when `DEMO_DATABASE_PATH` resolves to the same file as `DATABASE_PATH`.
2. If the demo file exists, opens it read-only and checks `PRAGMA application_id`.
   It deletes the file and its `-wal`/`-shm` siblings **only** when the id equals
   `DEMO_DB_APPLICATION_ID` (the fixed marker written at demo-DB creation).
   A foreign SQLite file (e.g. a copied live DB, which carries
   `LIVE_DB_APPLICATION_ID`) or a non-SQLite file is left untouched and the
   command exits 2.

Risk reduced: accidental destructive deletion of an unrelated database via a
typo/misconfiguration. Verified by `tests/unit/agent/test_demo.py`
(`test_demo_leaves_foreign_sqlite_file_untouched`,
`test_demo_leaves_non_sqlite_file_untouched`, `test_demo_refuses_same_file_as_live_db`).

### (b) `auth.py` — Bearer auth; non-ASCII token must be 401 not 500 (M2)

`_extract_bearer` parses the untrusted `Authorization` header defensively:
`None` for missing / oversized (`> MAX_AUTH_HEADER_CHARS = 512`) / non-`Bearer`
(case-insensitive scheme) / empty-token headers; otherwise it encodes the token
to **bytes** with `surrogatepass`. `_matches` compares bytes with
`hmac.compare_digest`. This matters because `hmac.compare_digest` raises
`TypeError` on non-ASCII `str` arguments — so comparing a raw `Bearer é…` token
as a string would surface as a generic exception → **500 `INTERNAL_ERROR`** with
a traceback and an inflated `LambdaError` metric. By returning `None`/bytes it is
a clean **401** instead. Both scope comparisons always run (constant work, so
timing never reveals which key was closer); invalid token → `Unauthorized` (401),
valid key wrong scope → `Forbidden` (403). Verified by
`tests/unit/cloud/test_auth.py` (non-ASCII, oversized, `Basic`, lowercase
`bearer`, empty token all → 401).

### (c) `serializer.py` — whitelist, IP scrubber, interface handling (M3)

`build_event` is an **explicit whitelist**: only `event_id`, `event_type`,
`schema_version`, `timestamp`, `source`, `status`, `network_status`, and the
scrubbed `checks`/`alerts`/`metrics` are uploaded. `scrub_ips` replaces a token
with `<ip>` **only when `ipaddress` accepts it**, so IPv4/IPv6 literals (incl.
`fe80::1%12`, `2001:db8::53`) are redacted while `16:42:03`, `C:\` and `87.0%`
survive. Interface names are handled structurally: the network rules refer to
interfaces **by count only** (`network_diagnostics.py`), so names stay in local
`facts` and never reach uploaded evidence; the scrubber is defense-in-depth for
any IP that still lands in a string.

**What is NOT sent:** interface names, DNS servers, gateway IPs, any IP literal,
physical-disk and GPU model strings (disks are referenced by position
`disk{index}`), and — per `docs/security.md` — browser history, documents,
keystrokes, screenshots, MAC addresses, serial numbers, user names. Verified by
`tests/unit/agent/test_serializer.py` (the `SENTINEL-IFACE`/`fe80::1%12`/
`2001:db8::53`/IPv4 sentinel leaks nothing; `C:`/`87.0%` survive). This is
data-minimization / privacy-by-design: minimize at the source, enforce via
whitelist + structural rules, and scrub as a backstop.

### Other controls

- **UUID device identity.** A random UUIDv4 at first run, stored `is_local=1`; a
  `DEVICE_ID` override is stored `is_local=0`; hostname is an attribute, never the
  key — so identity is independent of IP and hardware serials (`identity.py`).
- **Event IDs / idempotency.** UUIDv7 `event_id` + a frozen payload make the
  cloud conditional put exactly-once (same payload = duplicate, different payload
  = `EVENT_ID_CONFLICT`); see §11.
- **Secrets.** `Secret` wraps keys so `repr`/`str` are `***`; a logging redaction
  filter drops extras matching `key|token|secret|password|authorization`; a
  secret-leak test asserts a sentinel key appears in no log. Cloud keys live in
  SSM SecureStrings and are never logged.
- **Least privilege.** One IAM role per Lambda, no managed policies, no wildcard
  actions, log/DynamoDB/SSM resources scoped (see §10).
- **No invasive remote operations.** There is no remote command execution, no
  write-back to the host from the cloud; collectors and platform queries are
  read-only; the agent only ever POSTs minimized telemetry.

---

## 9. AWS Architecture Deep Dive

All configuration below is read from `infrastructure/template.yaml`.

- **HTTP API Gateway** (`AWS::Serverless::HttpApi`, payload format 2.0). Problem:
  a public HTTPS entry that routes/throttles cheaply. Config here:
  `StageName=!Ref Stage`, `DefaultRouteSettings` throttling
  (`ThrottleRateLimit`/`ThrottleBurstLimit`), JSON `AccessLogSettings` to a
  dedicated log group (captures `sourceIp`, `routeKey`, `status`, latency).
  Connects to the agent over `Authorization: Bearer`; routes to the four
  functions. Cert concepts: HTTP API vs REST API, stages, throttling, access logging.
- **Lambda ×4** (`health`, `device`, `telemetry`, `diagnostic`). Problem:
  stateless per-route compute with no servers. Config here: `python3.13`,
  `arm64`, `MemorySize=128`, `Timeout=10`, shared `CodeUri: ../src`, env vars
  (`TABLE_NAME`, `INGEST_KEY_PARAMETER`, `READ_KEY_PARAMETER`, and
  `DIAGNOSTIC_RETENTION_DAYS` for telemetry), each wired to HTTP API events for
  its route(s), each with its own `Role`. Cert concepts: event-driven compute,
  cold starts, proxy integration, per-function config, memory/arch cost.
- **DynamoDB** (`AWS::DynamoDB::Table`). Problem: durable, idempotent, pay-per-use
  key-value store. Config here: `BillingMode=PAY_PER_REQUEST`, keys `PK` (HASH) /
  `SK` (RANGE), `GSI1` (`GSI1PK`/`GSI1SK`, `ProjectionType: ALL`),
  `TimeToLiveSpecification` on `expires_at`. Cert concepts: single-table design,
  partition/sort keys, GSIs, on-demand vs provisioned, TTL, conditional writes.
- **CloudWatch**. Problem: observability without extra API calls. Config here:
  one `AWS::Logs::LogGroup` per function + an API access-log group, all
  `RetentionInDays=!Ref LogRetentionDays` (default 14) with
  `DeletionPolicy: Delete`. Metrics via EMF (`src/cloud/metrics.py`): namespace
  `DiagnosticGateway`, dimension set `[["Service","Function"]]`, 8 metric names.
  Cert concepts: Logs vs Metrics, EMF, retention, custom-metric billing.
- **SSM Parameter Store**. Problem: store the two API keys cheaply. Config here:
  parameter *names* are template parameters (`IngestKeyParameterName`,
  `ReadKeyParameterName`); the SecureString values are provisioned **outside the
  stack**. Loaded by `GetParameters(WithDecryption=True)`. Cert concepts:
  SecureString vs Secrets Manager, KMS `alias/aws/ssm` decrypt, parameter ARNs.
- **IAM**. Problem: least privilege per function. Config here: one explicit
  `AWS::IAM::Role` per function, no managed policies, no wildcard actions (see §10).
  Cert concepts: assume-role trust policy, inline policies, resource-scoped ARNs.
- **SAM**. Problem: declare the whole backend as reviewable code. Config here:
  `Transform: AWS::Serverless-2016-10-31`, `Globals.Function`, parameters,
  `Outputs` (`ApiBaseUrl`, `TableName`, `IngestKeyParameterName`). Validated
  offline with `cfn-lint`; never deployed from the repo. Cert concepts: IaC,
  CloudFormation transform/intrinsics, drift/state in CloudFormation.

---

## 10. IAM Review

Per `infrastructure/template.yaml`. Every role has a `lambda.amazonaws.com`
assume-role trust policy and inline policies only. Resource ARNs are built from
`${AWS::Partition}/${Region}/${AccountId}` so nothing is wildcarded.

| Function | Role | Permissions | Allowed resources | Reason |
|---|---|---|---|---|
| health | `HealthRole` | `logs:CreateLogStream`, `logs:PutLogEvents` | its own `/aws/lambda/${StackName}-health:*` log group | Liveness only; touches no backing service, so no DynamoDB/SSM at all. |
| device | `DeviceRole` | logs (own group) + `dynamodb:UpdateItem`,`GetItem`,`Query` + `ssm:GetParameters` | table ARN **and** `.../index/GSI1`; the two key parameter ARNs | Needs upsert (AP1), read one (AP2), list via GSI1 (AP3); auth needs both keys. No `PutItem`/`DeleteItem`. |
| telemetry | `TelemetryRole` | logs (own group) + `dynamodb:GetItem`,`PutItem`,`UpdateItem` + `ssm:GetParameters` | table ARN only (no index); the two key parameter ARNs | Needs device existence check (GetItem), conditional ingest (PutItem AP4), latest/last-seen (UpdateItem AP6/AP6b). No `Query`/`DeleteItem`; no GSI access. |
| diagnostic | `DiagnosticRole` | logs (own group) + `dynamodb:GetItem`,`Query` + `ssm:GetParameters` | table ARN only; the two key parameter ARNs | Needs device existence (GetItem) and newest-first list (Query AP5). Read-only on data; no writes, no GSI. |

Least-privilege notes: no role grants `dynamodb:DeleteItem` or `Scan`; log
permissions are scoped to each function's own group ARN; SSM is limited to
exactly the two parameter ARNs; KMS decrypt of the SecureStrings uses the managed
`alias/aws/ssm` key (a deploy-time dependency, not an explicit statement here).
Permissions were read from the template, not inferred.

---

## 11. DynamoDB Review

From `src/cloud/repository.py` and `docs/data-model.md`.

**Single-table design.** One table holds two entity types sharing a per-device
partition:
- **Partition key `PK`** = `DEVICE#<device_id>` for both entities.
- **Sort key `SK`** = `PROFILE` for the device profile; `DIAG#<event_id>` for an
  event. Because `event_id` is a time-ordered UUIDv7, `DIAG#…` sorts
  chronologically, so "newest first" is a reverse `Query` (`ScanIndexForward=False`).
- **GSI1** (`GSI1PK=DEVICE`, `GSI1SK=DEVICE#<id>`) is **sparse**: only profiles
  carry it, so "list devices" scans profiles only.
- **`entity`** attribute = `"device"` / `"diagnostic"`.

**Access patterns.** AP1 register/update (`update_item` upsert, idempotent); AP2
get one profile; AP3 list devices (Query GSI1, paginated); AP4 ingest
(conditional `put_item`); AP5 recent diagnostics (Query `begins_with(SK,'DIAG#')`
reverse); AP6 update latest status (guarded `update_item`); AP6b advance
`last_seen_at`.

**Conditional writes / idempotency.** `DiagnosticRepository.put_event` uses
`ConditionExpression="attribute_not_exists(PK)"` with
`ReturnValuesOnConditionCheckFailure="ALL_OLD"`. On a conflict it compares the
stored `payload_sha256` to the new one: equal → `DUPLICATE` (one item stored);
different → `CONFLICT` → the handler returns per-item `EVENT_ID_CONFLICT`. AP6's
`update_latest` is guarded by
`attribute_exists(PK) AND (attribute_not_exists(latest_event_id) OR latest_event_id < :eid)`
so an older event can't overwrite a newer one; a failed condition falls back to
`touch_last_seen`.

**TTL.** Events carry `expires_at` (epoch seconds = `received_at + retention_days·86400`,
default 30), and the table's `TimeToLiveSpecification` on `expires_at` expires
them for free. Profiles have no TTL.

**Public shaping.** `to_public` / `diagnostic_to_public` never return
`PK`/`SK`/`GSI1*`/`entity`/`payload_sha256`/`payload`, and convert DynamoDB
`Decimal` back to `int` (`_decimals_to_int`). Example stored diagnostic item
(`build_diagnostic_item`): `PK=DEVICE#id`, `SK=DIAG#<event_id>`,
`entity=diagnostic`, native `status`/`network_status`/`alert_count`/`timestamp`,
a compact-JSON `payload` holding `checks`/`alerts`/`metrics`, plus
`payload_sha256` and `expires_at`.

---

## 12. API Contract

From `src/cloud/handlers/*` and `docs/api.md`. All responses are
`application/json`. Error envelope: `{ "error": { code, message, request_id,
details? } }`. Size limits (`shared/schemas/common.py`): registration ≤ 8 KiB,
telemetry ≤ 256 KiB, ≤ 10 events/request, each event ≤ 32 KiB. Clock-skew window
= 300 s.

- **GET `/health`** — auth: none (`scope=None`). No body. 200 → `{status, service,
  version, time}`. No AWS calls; role carries logs only.
- **POST `/v1/devices`** — auth: `ingest`. Body = registration (`schema_version`,
  `device_id`, `device_name`, `os{name,version,architecture}`,
  `hardware{cpu_model?,logical_cpus,physical_cores?,memory_total_bytes}`,
  `agent_version`), validated by `validate_device_registration`. 201 created /
  200 updated → `{device_id, created, registered_at, updated_at}` (idempotent
  upsert AP1). Errors: 400 `VALIDATION_ERROR`, 401, 403, 413.
- **GET `/v1/devices`** — auth: `read`. Query `limit` (1–100, default 25),
  `cursor`. 200 → `{items:[public device], next_cursor}`. Errors: 400
  `INVALID_CURSOR`, 401, 403.
- **GET `/v1/devices/{device_id}`** — auth: `read`. `device_id` must match
  `DEVICE_ID_PATTERN` else 400. 200 → public device (`device_id, device_name, os,
  hardware, agent_version, registered_at, updated_at, last_seen_at, latest`);
  internal keys stripped. Errors: 400, 401, 403, 404 `NOT_FOUND`.
- **POST `/v1/telemetry`** — auth: `ingest`. Body = `{schema_version, device_id,
  events:[…1–10…]}`. Order: size check → JSON parse → envelope validate → GetItem
  device (missing → 409 `DEVICE_NOT_REGISTERED`) → per-event `validate_event` →
  conditional put → AP6/AP6b → per-item response. 200 → `{device_id, accepted,
  duplicates, rejected, results:[{event_id, status, error?}]}`. Per-item codes:
  `EVENT_ID_CONFLICT`, `CLOCK_SKEW`, `VALIDATION_ERROR`. Errors: 400
  `INVALID_JSON`/`VALIDATION_ERROR`, 401, 403, 409, 413, 503 `SERVICE_UNAVAILABLE`
  (transient DynamoDB mid-batch).
- **GET `/v1/devices/{device_id}/diagnostics`** — auth: `read`. Query `limit`
  (1–50, default 20), `cursor` (bound to `device_id`). Device missing → 404. 200
  → `{device_id, items:[{event_id, timestamp, received_at, source, status,
  network_status, alert_count, checks, alerts, metrics}], next_cursor}`. Errors:
  400 (bad id / `INVALID_CURSOR`), 401, 403, 404.

**Validation & error handling.** The shared schema is the single contract (the
agent pre-checks the same way). `@api_handler` maps exceptions to the B.14 table:
`ApiError` → its status/code/headers (401 adds `WWW-Authenticate: Bearer`, 503
adds `Retry-After: 5`); transient `ClientError` → 503 `SERVICE_UNAVAILABLE`;
anything else → generic 500 `INTERNAL_ERROR` (no traceback to the client).
Validation `details` carry field names + issues only, never values, and are
capped at 20.

---

## 13. Testing Strategy

The suite was run on the project `.venv`: **357 passed** (confirmed by
`python -m pytest -q`; `docs/engineering-report.md` cites the same figure, with
ruff/mypy/cfn-lint also clean). The point is not the count but *what the tests
prove*. Layout: `tests/unit/{agent,cloud,shared}`, `tests/integration`,
`tests/infra`, `tests/quality`, `tests/support`, `tests/fixtures`.

**Test types.**
- **Unit** — isolate one module with injected fakes (clocks, probers, SSM/transport stubs).
- **Integration** — end-to-end against real code paths: `test_sync_e2e.py` runs the agent `ApiClient` against the *real* Lambda handlers over a local HTTP server; `test_offline.py` runs real CLI commands with network primitives patched to fail.
- **moto** — `test_handlers_moto.py` invokes the real handlers with API Gateway v2 events against `moto.mock_aws` DynamoDB/SSM (no AWS account).
- **offline** — simulate no connectivity and assert local-first behavior + queue state.
- **failure paths** — error branches: storage failure, transient 5xx, 413 split, 409 re-registration, clock skew, delivery-uncertain.
- **contract/validation** — `shared/test_validation.py`, `agent/test_contract.py`: agent output always passes the cloud validator; `bool`-as-number and unknown fields rejected; `AGENT_VERSION_PATTERN` holds.
- **quality gates** — `test_import_boundaries.py` (AST scan: `shared` stdlib-only, `cloud` no `agent`, `agent` no `cloud`, `agent.config` no `agent.sync`), `test_secret_leak.py`, `test_diagrams_in_sync.py`, `test_adr_structure.py`.

**Grouped by what they prove.**
- *Functional behavior:* scenario outcomes (`test_demo.py` maps all six scenarios to exact status/alerts); classification (`test_network_classification.py`); CLI exit codes (`test_cli_exit_codes.py`); schema/serializer round-trips; repository access patterns under moto.
- *Security:* `test_auth.py` (non-ASCII/oversized/`Basic`/lowercase-bearer/empty → 401; valid-wrong-scope → 403; stale-key tolerance; dependency-unavailable); `test_serializer.py` M3 sentinel (no interface name/DNS/gateway/IP leaks; safe strings survive); `test_demo.py` M1 guards (foreign/non-SQLite files untouched, same-file refusal); `test_secret_leak.py`; `test_public_device.py` (no internal keys leak); `test_cursor.py` (tampered cursor → `INVALID_CURSOR`).
- *Integration:* `test_sync_e2e.py` (client ↔ real handlers), `test_handlers_moto.py` (handlers ↔ moto DynamoDB/SSM), `test_template.py` (SAM template assertions via cfn-lint decode).
- *Regression:* M1/M2/M3 tests exist specifically to pin the three MEDIUM fixes; the import-boundary test pins the local-first guarantee; `test_run_loop.py` pins the `--iterations` exit precedence.
- *Edge cases:* ping parsing fixtures (`tests/fixtures/ping/*`, en + pt-BR, timeout, unreachable), PowerShell numeric-vs-string enums (`tests/fixtures/powershell/*`), clock-skew boundary (299 s accepted), `None`-metric omission, delivery-uncertain vs offline.

---

## 14. Configuration and Environment

**Agent** (`src/agent/config/settings.py`, documented in `.env.example`).
Precedence: process env > `.env` file > built-in default. Exactly one `.env` is
loaded: `--env-file` > `./.env` > `<data dir>/.env`. Invalid values raise
`ConfigError` listing every bad key. Secrets are wrapped in `Secret`.

| Variable | Default | Limits | Consumed in |
|---|---|---|---|
| `API_BASE_URL` | "" (sync disabled) | https:// (http only for localhost) | `_validate_api_base_url`, `sync_enabled`, ApiClient |
| `AGENT_API_KEY` | "" | 32–256 chars; required when URL set | ApiClient auth header |
| `DEVICE_ID` | "" (generate) | `^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$` | `identity.resolve_device_id` |
| `DEVICE_NAME` | "" (hostname) | 1–64 chars | identity, registration |
| `TELEMETRY_INTERVAL_SECONDS` | 3600 | 300–86400 | `cmd_run` loop |
| `DATABASE_PATH` | `<data dir>/agent.db` | path | `local_db.connect` |
| `DEMO_DATABASE_PATH` | `<data dir>/demo.db` | path | `DemoRunner` |
| `LOG_LEVEL` | INFO | DEBUG/INFO/WARNING/ERROR | logging setup |
| `LOG_FILE` | `<data dir>/logs/agent.log` | path | logger |
| `RETRY_LIMIT` | 5 | 1–20 | `SyncSettings.retry_limit` → queue |
| `RETRY_BACKOFF_BASE_SECONDS` | 60 | 1–3600 | `BackoffPolicy.base_s` |
| `RETRY_BACKOFF_MAX_SECONDS` | 3600 | ≥ base, ≤ 86400 | `BackoffPolicy.max_s` |
| `SYNC_BATCH_SIZE` | 10 | 1–10 | `_pack`, `claim_due` |
| `SYNC_MAX_BATCHES_PER_CYCLE` | 5 | 1–100 | `run_cycle` loop bound |
| `HTTP_TIMEOUT_SECONDS` | 10.0 | 1–60 | ApiClient timeout |
| `CPU_SAMPLE_COUNT` | 3 | 1–10 | `collect_cpu` |
| `CPU_SAMPLE_INTERVAL_SECONDS` | 1.0 | 0.1–5 | `collect_cpu` |
| `CPU/MEMORY/DISK_*_PERCENT`, `LATENCY_WARNING_MS`, `PACKET_LOSS_*_PERCENT` | 90/90/85/95/150/10/30 | ranges; crit>warn, unstable>warn | `Thresholds` → rules/classification |
| `NETWORK_PROBE_COUNT` | 4 | 1–10 | probes |
| `NETWORK_PROBE_TIMEOUT_SECONDS` | 2.0 | 0.5–10 | probes |
| `INTERNET_TARGETS` | `1.1.1.1:443,8.8.8.8:443` | 1–5 `host:port` (IPv6 bracketed) | internet probes |
| `DNS_TEST_HOSTNAMES` | `example.com,aws.amazon.com` | 1–5 RFC-1123 | DNS probes |

**Cloud** (`src/cloud/config.py`): each handler declares `REQUIRED_ENV` and
lazily loads only what it needs. Loadable vars: `TABLE_NAME`,
`INGEST_KEY_PARAMETER`, `READ_KEY_PARAMETER`, `DIAGNOSTIC_RETENTION_DAYS`
(telemetry only; must be int ≥ 1). `LOG_LEVEL` (default INFO) and
`SERVICE_VERSION` (default 0.0.0; template sets 0.1.0) are always optional. A
missing required var raises `RuntimeError` → surfaces as a 500 (loud
misconfiguration). Infra parameters live in `template.yaml` (`Stage`, key names,
`DiagnosticRetentionDays`, `LogRetentionDays`, throttle limits).

**Local vs demo vs cloud differences.** *Local*: `.env`/env drives thresholds,
paths, probes; sync disabled unless `API_BASE_URL` set. *Demo*
(`DEMO_SYNC_SETTINGS`, `Thresholds()`, `DEMO_DEVICE_ID`): thresholds, sync
settings and identity are **constants** so `.env` cannot change output; endpoint
is unreachable `demo.invalid`. *Cloud*: configured entirely by Lambda env vars
from the SAM template; no `.env`.

---

## 15. Known Boundaries (confirmed)

Each item was confirmed against the repo (README limitations, engineering
report, template, code):

- **Not deployed to AWS.** The repo contains SAM + scripts but nothing auto-deploys; validation is offline `cfn-lint` only (`sam validate` not run — SAM CLI absent).
- **No Windows Service / scheduled task.** `run` is a foreground loop; there is no service/installer.
- **No remote command execution.** The cloud never instructs the agent; collectors/platform queries are read-only.
- **No web dashboard / UI.** Only the CLI + the read API.
- **No SNS / CloudWatch alarms.** Metrics are emitted; alarms/notifications are listed as future work.
- **No Linux/macOS collectors.** Collectors are Windows-first (`platform_support` is Windows CIM); the architecture allows others later.
- **No per-device credentials / mTLS.** A single shared ingest key (ADR-007); attribution relies on `sourceIp`.
- **No back-fill of disabled-sync runs.** Runs recorded while sync was off stay local-only (ADR-001).
- **No point-in-time recovery** on the table by default (cost trade-off, ADR-003).
- **No raw-ICMP packet loss.** "Packet loss" is the TCP-probe-failure rate (needs no admin rights).

---

## 16. AWS Certification Study Map

Relationship between the project and certification knowledge (no ranking between
certs). Certs abbreviated: **SAA** = Solutions Architect Associate, **DVA** =
Developer Associate, **CloudOps** = CloudOps/SysOps Engineer.

| Project component | AWS concept | Technical concept | Related cert(s) | File | What you must be able to explain |
|---|---|---|---|---|---|
| HTTP API Gateway | HTTP API vs REST API, stages, throttling, access logs | Public HTTPS entry, rate/burst, request routing | SAA, DVA, CloudOps | `infrastructure/template.yaml` (`HttpApi`) | Why HTTP API over REST here; how throttling bounds cost; what the access log captures |
| Lambda ×4 | Event-driven compute, proxy integration, cold starts | Stateless handlers, memory/arch, timeout | SAA, DVA | `src/cloud/handlers/*`, `src/cloud/http.py` | Request→handler flow; why 128 MB/arm64/10 s; warm-container caching |
| DynamoDB | Single-table design, GSI, TTL, conditional writes | PK/SK modeling, sparse index, idempotency | SAA, DVA | `src/cloud/repository.py`, `docs/data-model.md` | The 7 access patterns; how `event_id`+hash gives exactly-once; TTL expiry |
| CloudWatch | Logs vs Metrics, EMF, retention | Structured logs, custom metrics, dimensions | CloudOps, DVA | `src/cloud/metrics.py`, `docs/observability.md` | How EMF makes a metric from a log line; why `device_id` isn't a dimension; billing |
| SSM Parameter Store | SecureString, KMS decrypt, parameter ARNs | Secret retrieval + caching | SAA, DVA, CloudOps | `src/cloud/auth.py`, template params | SecureString vs Secrets Manager; `alias/aws/ssm`; stale-tolerant caching |
| IAM | Least privilege, inline policies, assume-role | Resource-scoped actions, no wildcards | SAA, DVA, CloudOps | `infrastructure/template.yaml` roles | Why one role per function; which actions each needs and why |
| SAM / CloudFormation | IaC, transforms, intrinsics, outputs | Declarative infra, offline validation | DVA, CloudOps | `infrastructure/template.yaml`, `samconfig.toml` | How SAM expands to CloudFormation; `cfn-lint` vs `sam validate` |
| API Gateway → Lambda → DynamoDB | Serverless request pipeline | Auth → validate → persist → respond | SAA, DVA | handlers + repository | The full path of one telemetry POST |
| Agent sync queue | Reliability / retries | Backoff+jitter, dead-letter, idempotency | DVA, CloudOps | `src/agent/sync/*`, `storage/queue.py` | Offline vs delivered-but-failed; why offline doesn't dead-letter |

---

## 17. Interview Knowledge Map

Questions you should be able to answer after studying the project. (Questions
only — do not answer them here.)

**Python**
- Why does the pipeline raise an explicit `ValueError` instead of `assert` for the identity/store invariant?
- What does the `Secret` type's `__repr__`/`__str__` return, and why?
- How does `run_collector` guarantee one collector failure never aborts the run?
- Why is `SyncSettings` defined in `config/settings.py` and not in `sync/`?

**Backend**
- How does the `@api_handler` decorator centralize auth + error mapping?
- Why do handlers cache settings/clients in module globals?
- What is the processing order inside `/v1/telemetry` and why that order?

**HTTP**
- Which HTTP statuses are transient vs permanent in the client classification, and why does order matter?
- Why does the transport refuse redirects?
- What makes a response "malformed" and why is retrying it safe?

**SQLite**
- What does WAL change about readers vs the single writer?
- How are migrations versioned, and what does `application_id` protect against?
- Why are run, results and queue event written in one `BEGIN IMMEDIATE`?

**Networking**
- What does this project's "packet loss" actually measure?
- How is network status classified first-match, and what triggers OFFLINE vs UNKNOWN?
- Why is interface evidence by count only?

**Security**
- Why must a non-ASCII bearer token be a 401 and not a 500?
- How is the IP scrubber precise enough to keep `C:\` and `16:42:03` but redact `fe80::1%12`?
- What data is deliberately never uploaded, and how is that enforced (whitelist vs structural vs scrub)?

**AWS**
- Why HTTP API over REST API here?
- Why `arm64`/128 MB/10 s, and what are the trade-offs?
- Where are the API keys stored and how are they decrypted?

**Serverless**
- What happens on a cold start for an authenticated route?
- How does the design keep idle cost near zero?

**DynamoDB**
- Explain the single-table keys and the sparse GSI1.
- How does the conditional put distinguish duplicate from conflict?
- How does TTL work and what is not TTL'd?

**IAM**
- Why one role per function instead of a shared role?
- Which DynamoDB actions does each function get, and which does it deliberately lack?

**Testing**
- What does the import-boundary test enforce and why does it matter?
- How do moto and the local-HTTP-server e2e test complement each other?
- Which tests pin the three MEDIUM fixes?

**Architecture**
- Walk a diagnostic run from hardware read to a DynamoDB item.
- Why is sync a separate step from the pipeline?
- What happens to a queued event during a week-long outage?

---

## 18. Developer Must Understand

A knowledge track (not a quality ranking).

**MUST UNDERSTAND**
- The full local flow: collect → diagnose → persist → enqueue, and that it works offline.
- The offline queue state machine and every transition owner (`storage/queue.py`).
- Retry/backoff/jitter and the rule that offline/auth/config aborts don't consume the budget while delivered-but-failed does.
- Idempotency: UUIDv7 `event_id` + frozen payload + conditional put (duplicate vs conflict).
- The API Gateway → Lambda → DynamoDB path for a telemetry POST, including auth and validation.
- IAM least privilege: one role per function and why each permission exists.
- The three MEDIUM fixes (M1 demo deletion guard, M2 401-not-500 auth, M3 IP scrub + interface-by-count).

**SHOULD UNDERSTAND**
- The shared schema as a single contract used by both sides.
- SSM SecureString loading + caching + stale tolerance.
- The HTTP response classification table and abort reasons.
- WAL, migrations, and the `application_id` live/demo marker.
- EMF metrics, the `[Service,Function]` dimension, and custom-metric billing.
- Demo mode's determinism and resource isolation.

**NICE TO UNDERSTAND**
- Cursor encoding/validation and why it is device-bound.
- The exit-code precedence (1 > 3 > 0) and interruptible sleep.
- Network classification causes/evidence generation.
- The deviations-from-spec list in `docs/architecture.md`.

---

## 19. Review Sequence

For each phase: objective · files · questions you should be able to answer.

**Phase 1 — Documentation.** Objective: build the mental model and the "why".
Files: `README.md`, `docs/architecture.md`, `docs/decisions/ADR-00{1..7}`,
`docs/engineering-report.md`. Questions: What problem does local-first solve?
Why serverless + DynamoDB + SAM? What does each ADR decide and reject?

**Phase 2 — Local Agent.** Objective: understand collection → persistence.
Files: `agent/main.py`, `commands.py`, `pipeline.py`, `collectors/*`,
`diagnostics/*`, `storage/local_db.py`, `storage/queue.py`. Questions: How does
`run_collector` isolate failures? What is written in one transaction? What are
the queue states and transitions?

**Phase 3 — Synchronization.** Objective: understand delivery + reliability.
Files: `sync/serializer.py`, `sync/client.py`, `sync/retry.py`, `sync/service.py`.
Questions: What is uploaded and what is scrubbed? How is each HTTP outcome
classified? Why doesn't an offline cycle dead-letter an event?

**Phase 4 — AWS Backend.** Objective: understand the cloud side.
Files: `cloud/auth.py`, `cloud/handlers/*`, `cloud/http.py`, `cloud/repository.py`,
`cloud/cursor.py`, `infrastructure/template.yaml`. Questions: How does auth
avoid a 500 on hostile input? What are the access patterns and conditional
writes? What permissions does each role hold?

**Phase 5 — Tests.** Objective: see what is actually proven.
Files: `tests/unit/*`, `tests/integration/{test_sync_e2e,test_offline}.py`,
`tests/integration/test_handlers_moto.py`, `tests/quality/*`, `tests/infra/test_template.py`.
Questions: What does the import-boundary test guarantee? Which tests pin M1/M2/M3?
How is offline behavior verified without a network?

**Phase 6 — Architecture Diagram.** Objective: internalize the whole system by
rebuilding it. Rebuild the architecture **manually in draw.io using official AWS
icons** (API Gateway, Lambda, DynamoDB, CloudWatch, SSM, IAM), mirroring
`diagrams/architecture.mmd`. Questions: Can you draw the local trust domain vs
the AWS domain and every arrow (HTTPS Bearer, Lambda→DynamoDB/SSM/CloudWatch)
from memory?

---

## 20. Final Audit Checklist

Use after reading. You should be able to:

- [ ] Explain the full local flow (collect → diagnose → persist → enqueue) offline.
- [ ] Explain the offline queue and every state transition.
- [ ] Explain retry/backoff/jitter and when the retry budget is (not) consumed.
- [ ] Explain idempotency via `event_id` + payload hash (duplicate vs conflict).
- [ ] Trace a telemetry POST through API Gateway → Lambda → DynamoDB.
- [ ] Explain IAM least privilege per function and why each permission exists.
- [ ] Explain how the two SSM keys are stored, decrypted and cached.
- [ ] Explain what the main tests prove (unit, moto, e2e, offline, quality gates).
- [ ] Explain the three MEDIUM fixes (M1 demo guard, M2 401-not-500, M3 scrub + interface-by-count).
- [ ] Explain WAL, migrations and the live/demo `application_id` marker.
- [ ] Explain EMF metrics, the dimension set, and custom-metric billing.
- [ ] State what the project does NOT do (§15) without guessing.
- [ ] Rebuild the architecture in draw.io with official AWS icons from memory.

---

## Source-of-Truth Verification

**Files/documents analyzed (read in full unless noted).**
- Agent: `main.py`, `commands.py`, `pipeline.py`, `identity.py`, `demo.py`, `collectors/base.py`, `diagnostics/engine.py`, `diagnostics/network_diagnostics.py`, `diagnostics/rules.py` (partial), `config/settings.py`, `storage/local_db.py`, `storage/queue.py`, `sync/{retry,client,service,serializer}.py`.
- Cloud: `auth.py`, `config.py`, `errors.py`, `http.py`, `metrics.py`, `repository.py`, `cursor.py`, `handlers/{health,device,telemetry,diagnostic,_support}.py`.
- Shared: `schemas/common.py` (and references to `schemas/device.py`, `schemas/telemetry.py`).
- Infra/config: `infrastructure/template.yaml`, `pyproject.toml`, `.env.example`.
- Docs: `README.md`, `docs/{architecture,api,data-model,security,threat-model,observability,cost,engineering-report}.md`, `docs/decisions/ADR-001..007.md`, `diagrams/{architecture,data-flow,sync-state-machine}.mmd`.
- Tests (read): `tests/unit/agent/{test_demo,test_serializer}.py`, `tests/unit/cloud/test_auth.py`, `tests/integration/test_offline.py`; the rest skimmed via the file list for §13.
- Review context: `.agents/tasks/design-review.md` (for the M1/M2/M3 history).
- Verification commands run (read-only): `pytest --collect-only -q` → 357 tests; `pytest -q` → **357 passed**.

**Divergences found (documentation vs implementation): none material.** The
three MEDIUM fixes (M1/M2/M3) described in `.agents/tasks/design-review.md` are
all implemented as described and verified against the code and their tests.
Noted precision points (consistent, but easy to misread):
- The retry-budget rule is correctly stated across ADR-005, `observability.md` and the failure matrix: only *provably-not-delivered* (OFFLINE) and auth/config aborts are uncounted; *delivery-uncertain* failures do consume the budget. The high-level README phrase "being offline … without consuming the retry budget" is accurate but omits this delivered-vs-not-delivered nuance, which the deeper docs make explicit. Flagged here so a reader does not over-generalize "any network failure is free."
- The design-review doc (`design-review.md`) describes the *pre-fix* problems (e.g. finding 4's demo identity conflict). The shipped `demo.py` resolves them (fixed `DEMO_DEVICE_ID` inserted directly, `resolve_device_id` not called), so the review doc is historical, not a description of current behavior.

**Points needing manual review (deploy-time; cannot be confirmed by reading
code offline).**
- KMS decrypt of the SSM SecureStrings via `alias/aws/ssm` (no explicit `kms:Decrypt` statement in the template; relies on the managed key policy).
- SAM resolving `CodeUri: ../src` and producing a working `arm64` artifact; the Lambda 128 MB / 10 s budget including SSM cold start.
- HTTP API access logging requiring the API Gateway service-linked role on first deploy.
- Whether the `python3.13` runtime's bundled boto3 supports `ReturnValuesOnConditionCheckFailure` (dates from 2023; low risk, unverified against the runtime image).

**Behavior that could not be confirmed by reading alone.** Real Windows
PowerShell/CIM output shapes and `ping` localization are covered by fixtures, not
by a live Windows run in this review; actual AWS behavior (throttling taking
effect, cold-start latency, TTL timing) is not exercised because nothing is
deployed. All AWS claims here are read from `infrastructure/template.yaml` and
the handlers, not from a running stack.
