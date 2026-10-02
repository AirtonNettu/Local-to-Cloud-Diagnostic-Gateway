# Security

> Language: English · [Português (Brasil)](security.pt-BR.md)

## Transport

All cloud traffic is HTTPS on the default `execute-api` endpoint (TLS 1.2+).
The agent's `urllib` transport verifies TLS certificates by default and refuses
every redirect, so the ingest key is never re-sent to a redirect target. A
redirect is treated as a configuration error.

## Authentication and authorization

Authentication is a Bearer API key. There are two scoped keys:

- `ingest` — used by agents to register and send telemetry (write).
- `read` — used by operators to list and read (read).

Keys are stored as SSM SecureStrings and loaded by the Lambda functions with one
`GetParameters(WithDecryption=True)` call, cached for five minutes, keeping a
stale value if a refresh fails (rotation without downtime). The token comes from
an untrusted header, so it is parsed defensively and compared on bytes with
`hmac.compare_digest`; both key comparisons always run so response timing never
reveals which key was closer. A non-ASCII token is rejected as 401, not 500.
Keys are never logged.

## IAM matrix

One explicit role per function, no managed policies, no wildcard actions.

| Function | Logs | DynamoDB | SSM |
|---|---|---|---|
| health | own log group only | none | none |
| device | own log group | `GetItem`, `UpdateItem`, `Query` (table + GSI1) | `GetParameters` on the two key ARNs |
| telemetry | own log group | `GetItem`, `PutItem`, `UpdateItem` (table) | `GetParameters` on the two key ARNs |
| diagnostic | own log group | `GetItem`, `Query` (table) | `GetParameters` on the two key ARNs |

Each log resource is scoped to that function's log-group ARN. KMS decryption of
the SecureStrings uses the AWS-managed `alias/aws/ssm` key.

## Secrets

The ingest key and read key never appear in code, logs, or `status` output. On
the agent they are wrapped in a `Secret` type whose `repr`/`str` return `***`,
and a logging redaction filter drops any extra key matching
`key|token|secret|password|authorization`. A secret-leak test runs a sync with a
sentinel key and asserts it appears in no captured log record or file.

## Input validation

The shared schema in `shared/schemas` is the single contract. The cloud enforces
it on every request and the agent pre-checks every payload it builds with the
same code, so a contract test proves agent output is always acceptable.
Validators report every problem at once, reject unknown fields, and reject
`bool` where a number is expected. Error details carry field names and issue
descriptions only, never field values.

## Data minimization

The agent uploads an explicit whitelist of fields. Evidence and messages are
scrubbed of IP literals (replaced with `<ip>`) and truncated to schema limits,
so interface names, DNS servers and gateway IPs never leave the host.
Physical-disk and GPU model strings stay in local facts and are structurally
excluded from checks, alerts and metrics (disks are referenced by position,
`disk{index}`). The agent never collects browser history, documents,
keystrokes, screenshots, MAC addresses, serial numbers or user names.

## sourceIp retention

The API access log retains the caller's `sourceIp`. This is a deliberate
exception to minimization: it is evidence for the stolen-key and abuse threats
(a single shared ingest key cannot otherwise be attributed to a caller). It is
kept only in the access-log group under the configured log retention (14 days by
default) and is never stored in DynamoDB or returned by the API.

## Trust boundaries (§44)

```text
LOCAL TRUST DOMAIN  (agent + local SQLite + .env on a user-controlled machine)
        │  HTTPS, Bearer token
        ▼
PUBLIC API          (anything reaching API Gateway is untrusted)
        │
        ▼
AWS APPLICATION     (trusted: Lambda code and its IAM roles)
        │
        ▼
DATABASE            (reachable only via the function roles)
```

- **Trusted**: the agent and its local database and `.env` on the user's own
  machine; the Lambda code and its roles.
- **Untrusted**: the public internet and any request that reaches API Gateway
  (authenticated or not) until auth and validation pass.
- DynamoDB and SSM are reachable only through the function roles, never
  directly from the internet.
