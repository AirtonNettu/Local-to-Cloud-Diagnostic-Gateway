# ADR-006: Infrastructure as code with AWS SAM

> Language: English · [Português (Brasil)](ADR-006-infrastructure-as-code-sam.pt-BR.md)

Status: accepted.

## Context

The backend must be reproducible and reviewable as code, deployable with
documented scripts, and validatable offline (no deployment happens from this
repository, and the SAM CLI is not installed on the development machine).

## Decision

Use AWS SAM (a CloudFormation transform with serverless shorthands). The template
declares the HTTP API, four functions with one explicit IAM role each, the
single DynamoDB table, per-function log groups, and parameters for stage, key
names and retention. Validation is offline with `cfn-lint`, which understands the
SAM transform. Deploy/teardown/validate scripts exist for both PowerShell and
Bash.

## Alternatives

- **AWS CDK**: imperative and powerful, but adds a Node.js toolchain and a CDK
  app for only four functions. Rejected.
- **Terraform**: excellent, but introduces a second language and a state backend
  to manage for a solo project. Rejected.
- **Console/click-ops**: not reproducible or reviewable. Rejected.

## Consequences

- The template maps one-to-one to the architecture diagram; no state backend to
  manage (CloudFormation holds state).
- Offline validation via `cfn-lint`; `sam validate` is noted as a future check
  once the SAM CLI is available.
- CloudFormation's verbosity for IAM roles is accepted in exchange for explicit
  least privilege.
