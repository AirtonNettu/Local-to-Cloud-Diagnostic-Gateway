# API reference

> Language: English · [Português (Brasil)](api.pt-BR.md)

Base URL: the deployed HTTP API stage URL, e.g.
`https://{api-id}.execute-api.{region}.amazonaws.com/{stage}`. All responses are
`application/json`. Authentication is a Bearer API key with two scopes: `ingest`
(write) and `read`. Keys live in SSM SecureStrings.

Error envelope (every error):

```json
{ "error": { "code": "VALIDATION_ERROR", "message": "...", "request_id": "...",
             "details": [ { "field": "events", "issue": "..." } ] } }
```

Common error codes: `INVALID_JSON` (400), `VALIDATION_ERROR` (400),
`UNAUTHORIZED` (401), `FORBIDDEN` (403), `NOT_FOUND` (404),
`DEVICE_NOT_REGISTERED` (409), `PAYLOAD_TOO_LARGE` (413),
`SERVICE_UNAVAILABLE` (503), `INTERNAL_ERROR` (500). Size limits:
registration body ≤ 8 KiB, telemetry body ≤ 256 KiB, up to 10 events per
request, each event ≤ 32 KiB.

---

## GET /health

- **Purpose**: liveness only; touches no backing dependency.
- **Auth**: none.
- **Request**: no body.
- **Response (200)**: `{ "status": "ok", "service": "diagnostic-gateway",
  "version": "0.1.0", "time": "2026-01-01T00:00:00.000Z" }`.
- **Errors**: none in normal operation.

```bash
curl https://API/health
```

---

## POST /v1/devices

- **Purpose**: register or update a device profile (idempotent upsert).
- **Auth**: `ingest`.
- **Request**:

```json
{ "schema_version": 1, "device_id": "my-device-01", "device_name": "Workstation",
  "os": { "name": "Windows", "version": "10.0.22631", "architecture": "AMD64" },
  "hardware": { "cpu_model": "...", "logical_cpus": 8, "physical_cores": 4,
                "memory_total_bytes": 17179869184 },
  "agent_version": "0.1.0" }
```

- **Response (201 created / 200 updated)**: `{ "device_id", "created",
  "registered_at", "updated_at" }`.
- **Errors**: 400 `VALIDATION_ERROR`, 401, 403, 413 `PAYLOAD_TOO_LARGE`.

```bash
curl -X POST https://API/v1/devices -H "Authorization: Bearer $INGEST_KEY" \
  -H "Content-Type: application/json" --data @registration.json
```

---

## GET /v1/devices

- **Purpose**: list device profiles, paginated (newest page via GSI1).
- **Auth**: `read`.
- **Request**: query `limit` (1–100, default 25), `cursor` (opaque).
- **Response (200)**: `{ "items": [ <public device> ], "next_cursor": null }`.
- **Errors**: 400 `INVALID_CURSOR`, 401, 403.

```bash
curl "https://API/v1/devices?limit=25" -H "Authorization: Bearer $READ_KEY"
```

---

## GET /v1/devices/{device_id}

- **Purpose**: one device profile.
- **Auth**: `read`.
- **Response (200)**: the public device object: `device_id`, `device_name`,
  `os`, `hardware`, `agent_version`, `registered_at`, `updated_at`,
  `last_seen_at`, and `latest` (newest event summary or `null`). Internal keys
  (`PK`, `SK`, `GSI1*`, `payload_sha256`) are never returned.
- **Errors**: 400 (bad id format), 401, 403, 404 `NOT_FOUND`.

```bash
curl "https://API/v1/devices/my-device-01" -H "Authorization: Bearer $READ_KEY"
```

---

## POST /v1/telemetry

- **Purpose**: ingest 1–10 diagnostic events (idempotent per `event_id`).
- **Auth**: `ingest`.
- **Request**:

```json
{ "schema_version": 1, "device_id": "my-device-01",
  "events": [ { "event_id": "<uuidv7>", "event_type": "diagnostic_run",
    "schema_version": 1, "timestamp": "2026-01-01T00:00:00.000Z",
    "source": "live", "status": "HEALTHY", "network_status": "HEALTHY",
    "checks": [], "alerts": [], "metrics": [] } ] }
```

- **Response (200)**: `{ "device_id", "accepted", "duplicates", "rejected",
  "results": [ { "event_id", "status": "accepted|duplicate|rejected",
  "error"? } ] }`. Per-item rejection codes include `EVENT_ID_CONFLICT`
  (reused id, different payload), `CLOCK_SKEW` (timestamp too far in the
  future), and `VALIDATION_ERROR`.
- **Errors**: 400 `INVALID_JSON` / `VALIDATION_ERROR`, 401, 403, 409
  `DEVICE_NOT_REGISTERED`, 413 `PAYLOAD_TOO_LARGE`, 503 `SERVICE_UNAVAILABLE`.

```bash
curl -X POST https://API/v1/telemetry -H "Authorization: Bearer $INGEST_KEY" \
  -H "Content-Type: application/json" --data @telemetry.json
```

---

## GET /v1/devices/{device_id}/diagnostics

- **Purpose**: recent diagnostic events for a device, newest first.
- **Auth**: `read`.
- **Request**: query `limit` (1–50, default 20), `cursor` (opaque).
- **Response (200)**: `{ "device_id", "items": [ { "event_id", "timestamp",
  "received_at", "source", "status", "network_status", "alert_count", "checks",
  "alerts", "metrics" } ], "next_cursor": null }`.
- **Errors**: 400 (bad id / `INVALID_CURSOR`), 401, 403, 404 `NOT_FOUND`.

```bash
curl "https://API/v1/devices/my-device-01/diagnostics?limit=20" \
  -H "Authorization: Bearer $READ_KEY"
```
