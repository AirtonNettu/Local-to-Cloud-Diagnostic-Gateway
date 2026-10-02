# Observability

> Language: English · [Português (Brasil)](observability.pt-BR.md)

Both sides emit one JSON object per log line. Secrets are redacted and arbitrary
objects are never serialized.

## Log fields

The `JsonFormatter` emits `timestamp` (ISO UTC), `level`, `component` (logger
name), `event`, `message`, and whitelisted context keys taken from `extra=`:

| Field | Meaning |
|---|---|
| `device_id` | the device the log line concerns |
| `request_id` | API Gateway request id / Lambda request id (cloud) |
| `run_id` | diagnostic run id |
| `event_id` | sync event id |
| `http_status` | status for an API-related line |
| `duration_ms` | operation duration where measured |
| `error`, `error_type` | error summary (never a secret) |
| counts | batch sizes and similar counters |

A redaction filter drops any extra key matching
`key|token|secret|password|authorization`. The agent writes a rotating JSON file
(`agent.log`) and a short text summary to stderr; the cloud writes JSON to
stdout, which Lambda ships to CloudWatch Logs.

## Metrics catalogue (EMF)

Cloud metrics use the Embedded Metric Format in the `DiagnosticGateway`
namespace with a single dimension set `[["Service", "Function"]]`. `device_id`
is deliberately never a dimension (high cardinality, cost).

| Metric | Emitted when |
|---|---|
| `DeviceRegistered` | a device register/update succeeds |
| `TelemetryAccepted` | an event is newly stored |
| `TelemetryDuplicate` | an event is a duplicate |
| `TelemetryRejected` | an event is rejected (validation / conflict) |
| `ValidationError` | a request fails validation / is malformed / too large |
| `AuthFailure` | a 401 or 403 |
| `DynamoDBError` | a DynamoDB client/throttling error |
| `LambdaError` | an unexpected handler exception (mapped to 500) |

EMF turns a log line into a metric without a separate API call. Custom metrics
are billed per name × dimension per month (see [cost.md](cost.md)).

## Agent-side sync-failure split

The agent distinguishes two kinds of sync failure so an outage is not treated
like a server fault:

- **Offline** (`ConnectivityError` → `OFFLINE` attempt): the request was
  provably not delivered (DNS failure, connection refused, network unreachable,
  connect timeout, TLS interception). The event stays PENDING/FAILED with its
  attempt count and `next_attempt_at` unchanged; the cycle aborts with
  `aborted="offline"` and logs `event=sync_offline`. These attempts never
  consume `RETRY_LIMIT`.
- **Delivered-but-failed** (`TransientSyncError` / server 5xx / 429 / malformed
  response / delivery-uncertain): the request was (or may have been) sent. The
  event FAILs with backoff and reaches DEAD_LETTER at `RETRY_LIMIT`.

Every attempt is recorded in `sync_attempts` with its `outcome` (`ACCEPTED`,
`DUPLICATE`, `REJECTED`, `TRANSIENT_ERROR`, `OFFLINE`, `AUTH_ERROR`,
`CONFIG_ERROR`, `INTERRUPTED`), so `queue` and `status` can explain exactly why
an event has not synced.
