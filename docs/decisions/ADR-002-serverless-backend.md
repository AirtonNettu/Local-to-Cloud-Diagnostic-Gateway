# ADR-002: Serverless backend

> Language: English · [Português (Brasil)](ADR-002-serverless-backend.pt-BR.md)

Status: accepted.

## Context

The backend ingests small, spiky bursts of telemetry from a handful of devices
and must cost almost nothing when idle. It is a portfolio project maintained by
one person, so operational overhead should be minimal.

## Decision

Use an AWS serverless backend: HTTP API Gateway in front of four small Lambda
functions, with DynamoDB for storage, SSM for secrets and CloudWatch for
observability. There are no servers, containers or capacity to manage.

## Alternatives

- **Containers (ECS/Fargate) or EC2**: always-on cost and patching for a
  low-volume workload. Rejected.
- **A single monolithic Lambda**: simpler routing but one over-broad IAM role;
  per-function roles give least privilege. Rejected.

## Consequences

- Near-zero idle cost; cost scales with requests (see [cost.md](../cost.md)).
- Each function gets its own least-privilege role.
- The design is AWS-specific; portability is traded for simplicity.
- Cold starts are acceptable for an hourly, asynchronous ingest path.
