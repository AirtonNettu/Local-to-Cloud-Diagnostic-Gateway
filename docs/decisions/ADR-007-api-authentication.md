# ADR-007: API authentication

> Language: English · [Português (Brasil)](ADR-007-api-authentication.pt-BR.md)

Status: accepted.

## Context

The API needs authentication that is simple to operate for a single-author
project, separates write from read access, keeps secrets out of code and logs,
and is safe to compare against hostile input. Per-device credentials and a full
authorizer are more than v1 needs.

## Decision

Use a Bearer API key with two scopes: `ingest` (agents write) and `read`
(operators read). Both keys are SSM SecureStrings, loaded with one
`GetParameters(WithDecryption=True)` call, cached for five minutes, and kept
(stale) if a refresh fails so rotation causes no downtime. The token is parsed
defensively and compared on bytes with `hmac.compare_digest`; both scope
comparisons always run so timing reveals nothing, and a non-ASCII token is a 401
rather than a 500. Scope enforcement lives in the `@api_handler` decorator.

## Alternatives

- **A Lambda authorizer / Cognito / IAM SigV4**: stronger but heavier to operate
  than a two-key model needs for v1. Deferred to future work.
- **A single key for all routes**: no separation between write and read.
  Rejected.
- **Per-device credentials**: better attribution but more key management; a
  documented residual risk, deferred.

## Consequences

- Simple operation: two parameters to provision and rotate.
- A leaked ingest key can spoof device IDs until rotated; `sourceIp` in the
  access log is the attribution evidence (see [security.md](../security.md) and
  the [threat model](../threat-model.md)).
- Constant-time comparison and strict parsing make auth safe against hostile
  headers.
