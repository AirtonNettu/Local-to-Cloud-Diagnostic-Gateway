# Threat model

> Language: English · [Português (Brasil)](threat-model.pt-BR.md)

Nine threats, each with impact, mitigation and residual risk. The system uses a
single shared ingest key (per-device credentials are future work), which shapes
several residual risks below.

### 1. Stolen or leaked ingest key

- **Impact**: an attacker can submit telemetry and spoof other device IDs.
- **Mitigation**: SecureString storage, HTTPS only, `Secret` wrapper and log
  redaction on the agent, access log retains `sourceIp` as evidence, key
  rotation supported without downtime.
- **Residual**: a leaked key is usable until rotated; attribution relies on
  `sourceIp`. Per-device credentials would remove this; accepted for v1.

### 2. Replay of a captured request

- **Impact**: a captured telemetry request could be re-sent.
- **Mitigation**: idempotent ingestion keyed on `event_id` (conditional put) and
  a clock-skew window reject future timestamps; a replay is a no-op duplicate.
- **Residual**: a captured request can be replayed as a no-op; it cannot create
  a second stored item or alter an existing one.

### 3. Man-in-the-middle / redirect to a hostile host

- **Impact**: interception or theft of the bearer key.
- **Mitigation**: TLS certificate verification by default; the transport refuses
  all redirects so the key is never copied to another host; a redirect is a
  `CONFIG_ERROR`.
- **Residual**: a host-level trusted-CA compromise is out of scope.

### 4. Credential theft from logs or output

- **Impact**: a key could leak through logs or `status`.
- **Mitigation**: `Secret` wrapper (`***`), a redaction filter on log extras, and
  a secret-leak test with a sentinel key.
- **Residual**: an attacker with local filesystem access to the plaintext `.env`
  already controls the host; this is outside the API's trust boundary.

### 5. Injection via telemetry payloads

- **Impact**: malformed or oversized payloads could crash a handler or poison
  storage.
- **Mitigation**: strict schema validation, unknown-field rejection, size limits
  (8 KiB registration, 256 KiB telemetry, 32 KiB per event), `bool`-as-number
  rejection; payloads are stored as JSON strings, not evaluated.
- **Residual**: well-formed but misleading values are accepted; they are
  diagnostic data, not executed.

### 6. Denial of service / cost amplification

- **Impact**: a flood of requests raises cost or latency.
- **Mitigation**: API Gateway throttling (rate + burst), small per-request
  limits, on-demand DynamoDB, 128 MB short-timeout functions.
- **Residual**: a determined attacker with a valid key can still generate cost;
  bounded by throttling and alarms (alarms are future work).

### 7. Privilege escalation across functions

- **Impact**: one compromised function reaching another's data.
- **Mitigation**: one least-privilege role per function, no wildcard actions,
  log resources scoped per function, SSM scoped to the two parameter ARNs.
- **Residual**: all functions can read the two keys (they must authenticate);
  acceptable given the shared-key model.

### 8. Data exposure through the read API

- **Impact**: a read key could expose internal storage shapes or PII.
- **Mitigation**: a single `to_public` mapping strips internal keys; the agent
  minimizes and scrubs data before upload, so there is little sensitive content
  to expose; a unit test asserts no internal keys leak.
- **Residual**: a leaked read key exposes device inventory and diagnostics
  (non-PII) until rotated.

### 9. Tampered pagination cursor

- **Impact**: a crafted cursor could read across devices.
- **Mitigation**: the diagnostics cursor is bound to its `device_id` and
  validated on decode; a tampered cursor is `INVALID_CURSOR` (400).
- **Residual**: none beyond what the read scope already allows.
