# Engineering report

> Language: English · [Português (Brasil)](engineering-report.pt-BR.md)

## Architecture summary

A Windows-first Python agent runs a `collect → diagnose → evaluate → persist (+
enqueue) → report` pipeline entirely offline, storing every run in SQLite.
Selected, minimized telemetry is queued locally and synchronized to an AWS
serverless backend (HTTP API Gateway → four Lambda functions → single-table
DynamoDB, with CloudWatch logs/metrics and SSM-stored keys). The agent, cloud
and shared code are three packages under `src/`; the shared schema is the API
contract that both sides use.

## Components

- **agent**: CLI, pipeline, collectors, a read-only Windows platform module,
  diagnostics (probes, rules, health), SQLite storage, the sync queue and
  service, configuration and logging.
- **cloud**: HTTP parsing + the `@api_handler` error mapping, Bearer auth with
  two SSM-backed scopes, the DynamoDB repository, EMF metrics, and four handlers
  (health, device, telemetry, diagnostic).
- **shared**: frozen models, hand-written validators, and UUIDv7 / ISO-time /
  JSON-logging utilities.

## Data flow

Hardware readings become typed collector facts, the engine turns them into
checks/alerts/metrics and an overall status, the result is persisted and (if
sync is enabled) enqueued as a frozen, IP-scrubbed payload. A sync cycle delivers
byte-packed batches over HTTPS with a Bearer token; the Lambda authenticates,
validates against the shared schema, and writes an idempotent item per
`event_id` to DynamoDB. Logs and EMF metrics go to CloudWatch.

## Security

HTTPS with certificate verification and no redirects; a Bearer key with `ingest`
and `read` scopes stored as SSM SecureStrings and compared in constant time on
bytes; one least-privilege IAM role per function with no wildcard actions;
strict schema validation; data minimization and IP scrubbing before upload. See
[security.md](security.md) and the [threat model](threat-model.md).

## Reliability

Local-first: every local command works with no network. The sync queue is
durable with a bounded, jittered backoff and a DEAD_LETTER state. Being offline
records an `OFFLINE` attempt without consuming the retry budget, so a long outage
never dead-letters an event; sync resumes on the first cycle after connectivity
returns. Crash recovery reclaims expired `SYNCING` leases. Ingestion is
idempotent, so retries and duplicates store exactly one item.

## AWS

HTTP API Gateway (cheap, low-latency public entry), Lambda (stateless per-route
compute), DynamoDB (serverless key-value with TTL), SSM Parameter Store (free
SecureStrings), CloudWatch (logs + EMF metrics). Each is justified in
[architecture.md](architecture.md).

## Cost

Pay-per-use with conservative defaults: on-demand DynamoDB, 128 MB `arm64`
functions, 14-day log retention, TTL on events, and a small fixed set of EMF
metrics with one low-cardinality dimension. See [cost.md](cost.md), including the
note that EMF custom metrics are billed per name × dimension per month (~10–12
billable metrics in active months).

## Testing

Everything is verified locally with no AWS account: unit tests across agent,
cloud and shared; moto-backed cloud integration tests invoking the real handlers
with API Gateway v2 events; an end-to-end test of the agent sync client against
the real handlers over a local `ThreadingHTTPServer`; offline scenarios;
infrastructure assertions on the SAM template; and quality gates (import
boundaries, secret-leak, diagram/ADR structure).

Results from the final verification run on the project `.venv` (Python 3.14.6,
Windows PowerShell 5.1):

```text
pytest:     357 passed in ~55s
ruff check: All checks passed!
mypy src:   Success: no issues found in 65 source files
cfn-lint:   infrastructure/template.yaml passes (no findings).
```

The two previously-skipped quality tests (`test_diagrams_in_sync` and
`test_adr_structure`) now run and pass, because the diagrams and ADRs this
feature adds exist. The baseline before this feature was 355 passed, 2 skipped;
adding the diagrams and ADRs flips those two skips to passes (357 passed, 0
skipped). `cfn-lint` runs as `cfn-lint infrastructure/template.yaml` because the
pinned package exposes a console script rather than a `-m cfnlint` module entry.

## Known limitations

- Windows-only collectors; the architecture allows other platforms later.
- A single shared ingest key (no per-device credentials or mTLS).
- No web dashboard, alerting, or remote commands.
- Runs recorded while sync was disabled are not back-filled.
- `sam validate` is not run here (the SAM CLI is not installed); `cfn-lint` is
  used for offline IaC validation.

## Future improvements

Per-device credentials, a Lambda authorizer, a read dashboard, SNS/CloudWatch
alarms, Linux/macOS collectors, and point-in-time recovery for the table.

# What the developer must understand

Before presenting this project, be comfortable explaining each of these and
where it appears in the code:

- **Python modules, classes, functions, type hints, exceptions**: the `src/`
  package layout, frozen dataclasses in `shared/models`, the typed collector
  results, and the exception hierarchies in `cloud/errors.py` and
  `agent/sync/client.py`.
- **HTTP, REST, JSON, HTTP status codes**: the `/v1` contract in
  [api.md](api.md) and the ordered response-classification table in
  `agent/sync/client.py`.
- **API Gateway, Lambda, DynamoDB, IAM, CloudWatch**: the four handlers, the
  single-table design in [data-model.md](data-model.md), the per-function roles
  in the SAM template, and the EMF metrics.
- **Authentication and authorization**: the two-scope Bearer model in
  `cloud/auth.py` (constant-time byte comparison, SSM-backed keys).
- **SQLite, queues, retries, idempotency**: the local schema, the sync-queue
  state machine in `agent/storage/queue.py`, the backoff policy, and the
  conditional-put idempotency in `cloud/repository.py`.
- **Observability**: structured JSON logging with redaction and EMF metrics
  ([observability.md](observability.md)).
- **Edge computing and serverless architecture**: why diagnostics run locally
  and the backend is stateless and pay-per-use (ADR-001, ADR-002).
- **Infrastructure as code**: the SAM template and offline `cfn-lint` validation
  (ADR-006).
- **Network diagnostics, DNS, TCP/IP**: the probes and classification in
  `agent/diagnostics`, and the TCP-probe-failure-rate note in
  [architecture.md](architecture.md).
