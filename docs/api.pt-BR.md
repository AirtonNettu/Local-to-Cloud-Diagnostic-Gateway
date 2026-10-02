# Referência da API

> Idioma: Português (Brasil) · [English](api.md)

URL base: a URL do stage do HTTP API implantado, por exemplo
`https://{api-id}.execute-api.{region}.amazonaws.com/{stage}`. Todas as respostas
são `application/json`. A autenticação é uma chave de API Bearer com dois
escopos: `ingest` (escrita) e `read` (leitura). As chaves ficam em SSM
SecureStrings.

Envelope de erro (todo erro):

```json
{ "error": { "code": "VALIDATION_ERROR", "message": "...", "request_id": "...",
             "details": [ { "field": "events", "issue": "..." } ] } }
```

Códigos de erro comuns: `INVALID_JSON` (400), `VALIDATION_ERROR` (400),
`UNAUTHORIZED` (401), `FORBIDDEN` (403), `NOT_FOUND` (404),
`DEVICE_NOT_REGISTERED` (409), `PAYLOAD_TOO_LARGE` (413),
`SERVICE_UNAVAILABLE` (503), `INTERNAL_ERROR` (500). Limites de tamanho: corpo de
registro ≤ 8 KiB, corpo de telemetria ≤ 256 KiB, até 10 eventos por requisição,
cada evento ≤ 32 KiB.

---

## GET /health

- **Finalidade**: apenas liveness; não toca nenhuma dependência de backend.
- **Auth**: nenhuma.
- **Requisição**: sem corpo.
- **Resposta (200)**: `{ "status": "ok", "service": "diagnostic-gateway",
  "version": "0.1.0", "time": "2026-01-01T00:00:00.000Z" }`.
- **Erros**: nenhum em operação normal.

```bash
curl https://API/health
```

---

## POST /v1/devices

- **Finalidade**: registrar ou atualizar um perfil de dispositivo (upsert
  idempotente).
- **Auth**: `ingest`.
- **Requisição**:

```json
{ "schema_version": 1, "device_id": "my-device-01", "device_name": "Workstation",
  "os": { "name": "Windows", "version": "10.0.22631", "architecture": "AMD64" },
  "hardware": { "cpu_model": "...", "logical_cpus": 8, "physical_cores": 4,
                "memory_total_bytes": 17179869184 },
  "agent_version": "0.1.0" }
```

- **Resposta (201 criado / 200 atualizado)**: `{ "device_id", "created",
  "registered_at", "updated_at" }`.
- **Erros**: 400 `VALIDATION_ERROR`, 401, 403, 413 `PAYLOAD_TOO_LARGE`.

```bash
curl -X POST https://API/v1/devices -H "Authorization: Bearer $INGEST_KEY" \
  -H "Content-Type: application/json" --data @registration.json
```

---

## GET /v1/devices

- **Finalidade**: listar perfis de dispositivo, paginado (página via GSI1).
- **Auth**: `read`.
- **Requisição**: query `limit` (1–100, padrão 25), `cursor` (opaco).
- **Resposta (200)**: `{ "items": [ <device público> ], "next_cursor": null }`.
- **Erros**: 400 `INVALID_CURSOR`, 401, 403.

```bash
curl "https://API/v1/devices?limit=25" -H "Authorization: Bearer $READ_KEY"
```

---

## GET /v1/devices/{device_id}

- **Finalidade**: um perfil de dispositivo.
- **Auth**: `read`.
- **Resposta (200)**: o objeto público do dispositivo: `device_id`,
  `device_name`, `os`, `hardware`, `agent_version`, `registered_at`,
  `updated_at`, `last_seen_at` e `latest` (resumo do evento mais recente ou
  `null`). Chaves internas (`PK`, `SK`, `GSI1*`, `payload_sha256`) nunca são
  retornadas.
- **Erros**: 400 (formato de id inválido), 401, 403, 404 `NOT_FOUND`.

```bash
curl "https://API/v1/devices/my-device-01" -H "Authorization: Bearer $READ_KEY"
```

---

## POST /v1/telemetry

- **Finalidade**: ingerir de 1 a 10 eventos de diagnóstico (idempotente por
  `event_id`).
- **Auth**: `ingest`.
- **Requisição**:

```json
{ "schema_version": 1, "device_id": "my-device-01",
  "events": [ { "event_id": "<uuidv7>", "event_type": "diagnostic_run",
    "schema_version": 1, "timestamp": "2026-01-01T00:00:00.000Z",
    "source": "live", "status": "HEALTHY", "network_status": "HEALTHY",
    "checks": [], "alerts": [], "metrics": [] } ] }
```

- **Resposta (200)**: `{ "device_id", "accepted", "duplicates", "rejected",
  "results": [ { "event_id", "status": "accepted|duplicate|rejected",
  "error"? } ] }`. Os códigos de rejeição por item incluem `EVENT_ID_CONFLICT`
  (id reusado, payload diferente), `CLOCK_SKEW` (timestamp muito no futuro) e
  `VALIDATION_ERROR`.
- **Erros**: 400 `INVALID_JSON` / `VALIDATION_ERROR`, 401, 403, 409
  `DEVICE_NOT_REGISTERED`, 413 `PAYLOAD_TOO_LARGE`, 503 `SERVICE_UNAVAILABLE`.

```bash
curl -X POST https://API/v1/telemetry -H "Authorization: Bearer $INGEST_KEY" \
  -H "Content-Type: application/json" --data @telemetry.json
```

---

## GET /v1/devices/{device_id}/diagnostics

- **Finalidade**: eventos de diagnóstico recentes de um dispositivo, mais novos
  primeiro.
- **Auth**: `read`.
- **Requisição**: query `limit` (1–50, padrão 20), `cursor` (opaco).
- **Resposta (200)**: `{ "device_id", "items": [ { "event_id", "timestamp",
  "received_at", "source", "status", "network_status", "alert_count", "checks",
  "alerts", "metrics" } ], "next_cursor": null }`.
- **Erros**: 400 (id inválido / `INVALID_CURSOR`), 401, 403, 404 `NOT_FOUND`.

```bash
curl "https://API/v1/devices/my-device-01/diagnostics?limit=20" \
  -H "Authorization: Bearer $READ_KEY"
```
