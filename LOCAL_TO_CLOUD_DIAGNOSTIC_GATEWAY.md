# Local-to-Cloud Diagnostic Gateway

## Technical Specification, Architecture Plan and Implementation Instructions

**Project type:** Edge Computing + Cloud + Infrastructure Diagnostics
**Primary language:** Python
**Cloud provider:** AWS
**Primary objective:** Build a production-style local computer diagnostic agent capable of collecting hardware, operating system and network telemetry, processing diagnostics locally, and optionally synchronizing selected telemetry with an AWS serverless backend.

---

# 1. PROJECT VISION

Build a real technical platform that connects a local computer to a cloud backend.

The local computer acts as an **edge diagnostic node**.

The AWS environment acts as the **centralized cloud backend** responsible for receiving, storing, observing and exposing diagnostic information.

The system must be designed around an important architectural principle:

> The local diagnostic agent must remain useful even when cloud connectivity is unavailable.

The cloud is an extension of the diagnostic system, not a mandatory dependency for every local operation.

The final project must demonstrate practical knowledge of:

* Python
* Windows system diagnostics
* computer hardware
* networking
* REST APIs
* AWS serverless architecture
* API Gateway
* AWS Lambda
* DynamoDB
* CloudWatch
* IAM
* authentication
* logging
* monitoring
* fault tolerance
* offline operation
* synchronization
* testing
* documentation
* architecture decisions
* security
* infrastructure as code

The project must be suitable for presentation in a professional software/cloud engineering portfolio.

---

# 2. IMPORTANT IMPLEMENTATION PRINCIPLE

Do NOT treat this project as a simple CRUD application.

The core problem is:

> How can a local computer collect useful diagnostic information, operate independently, survive temporary network failures, and synchronize relevant telemetry with a cloud backend in a secure and cost-conscious way?

The architecture must reflect this problem.

Avoid unnecessary AWS services.

Avoid creating infrastructure simply because a service exists.

Every cloud component must have a documented reason for existing.

---

# 3. PROJECT GOALS

The system must be capable of:

1. Identifying the local machine.
2. Collecting hardware information.
3. Collecting operating-system information.
4. Collecting storage information.
5. Collecting memory information.
6. Collecting CPU information.
7. Collecting network information.
8. Performing network diagnostics.
9. Generating health indicators.
10. Detecting configurable abnormal conditions.
11. Persisting local diagnostic information.
12. Operating without internet connectivity.
13. Queueing cloud synchronization events locally.
14. Synchronizing queued events when connectivity returns.
15. Sending selected telemetry to AWS.
16. Validating received data.
17. Storing cloud telemetry.
18. Exposing diagnostic information through an API.
19. Producing structured logs.
20. Providing observability.
21. Providing automated tests.
22. Providing clear technical documentation.
23. Providing an architecture diagram.
24. Providing an explanation of all major architectural decisions.

---

# 4. NON-GOALS

The first version must NOT attempt to become:

* a complete remote desktop system;
* antivirus software;
* an enterprise MDM;
* a complete ITSM platform;
* a hardware overclocking tool;
* a BIOS management system;
* a remote command execution platform;
* a system capable of silently changing the user's computer;
* a commercial monitoring SaaS.

The system is primarily diagnostic and observational.

Do not implement destructive or invasive operations.

---

# 5. TARGET ENVIRONMENT

The initial agent should target:

* Windows 10/11
* Python 3.x
* x86-64 systems

The architecture should make future Linux support possible, but Linux support is not required for version 1.

Platform-specific code must be isolated whenever possible.

---

# 6. HIGH-LEVEL ARCHITECTURE

The initial architecture should follow this conceptual model:

```text
                         LOCAL COMPUTER
                              │
                              ▼
                  ┌─────────────────────┐
                  │ Diagnostic Agent    │
                  │                     │
                  │ Hardware Collector  │
                  │ OS Collector        │
                  │ Storage Collector   │
                  │ Network Collector   │
                  │ Diagnostic Engine   │
                  │ Health Evaluator    │
                  │ Local Storage       │
                  │ Sync Queue          │
                  └──────────┬──────────┘
                             │
                      HTTPS / REST API
                             │
                             ▼
                    ┌─────────────────┐
                    │   API Gateway   │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │     Lambda      │
                    │ Ingestion/API   │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │    DynamoDB     │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │   CloudWatch    │
                    │ Logs / Metrics  │
                    └─────────────────┘
```

The architecture must distinguish between:

## Edge responsibilities

The local agent should be responsible for:

* collecting raw system information;
* performing local diagnostics;
* detecting local conditions;
* maintaining local state;
* maintaining the offline queue;
* retrying synchronization;
* reducing unnecessary cloud traffic.

## Cloud responsibilities

AWS should be responsible for:

* receiving telemetry;
* validating requests;
* storing selected information;
* exposing API operations;
* centralized logging;
* cloud-side monitoring;
* centralized device information.

---

# 7. ARCHITECTURAL PRINCIPLE: LOCAL-FIRST

The application must continue functioning when:

```text
Internet = unavailable
```

The following operations must still work:

* hardware scan;
* OS scan;
* storage scan;
* memory scan;
* CPU scan;
* network diagnostics;
* local health evaluation;
* local report generation;
* local persistence.

Cloud synchronization must become a secondary operation.

Example:

```text
Internet available

Diagnostic
    ↓
Local storage
    ↓
Sync
    ↓
AWS
```

When internet connectivity fails:

```text
Diagnostic
    ↓
Local storage
    ↓
Pending queue
    ↓
WAIT
```

When connectivity returns:

```text
Pending queue
    ↓
Retry
    ↓
AWS
    ↓
Success
    ↓
Mark synchronized
```

---

# 8. FUNCTIONAL COMPONENTS

The Python application should be divided into clear modules.

Suggested structure:

```text
src/
├── agent/
│   ├── collectors/
│   │   ├── cpu.py
│   │   ├── memory.py
│   │   ├── storage.py
│   │   ├── system.py
│   │   ├── network.py
│   │   └── hardware.py
│   │
│   ├── diagnostics/
│   │   ├── health.py
│   │   ├── network_diagnostics.py
│   │   └── rules.py
│   │
│   ├── storage/
│   │   ├── local_db.py
│   │   └── queue.py
│   │
│   ├── sync/
│   │   ├── client.py
│   │   ├── retry.py
│   │   └── serializer.py
│   │
│   ├── config/
│   │   └── settings.py
│   │
│   ├── logging/
│   │   └── logger.py
│   │
│   └── main.py
│
├── shared/
│   ├── models/
│   ├── schemas/
│   └── utils/
│
└── tests/
```

The exact structure may be adjusted if a better architecture is identified.

Any deviation from this structure must be documented.

---

# 9. HARDWARE COLLECTION

The agent must collect useful hardware information without performing invasive operations.

Minimum target information:

## CPU

* processor name;
* logical processors;
* physical cores when available;
* current utilization;
* average utilization;
* basic frequency information when available.

## Memory

* total RAM;
* available RAM;
* used RAM;
* percentage utilization.

## Storage

For each relevant storage device:

* device identifier when available;
* capacity;
* available space;
* percentage used;
* filesystem;
* basic health information when safely available.

Do not implement destructive disk tests.

## System

Collect:

* hostname;
* operating system;
* OS version;
* architecture;
* boot time when available;
* uptime.

## GPU

Collect basic information when available.

GPU collection must fail gracefully if information cannot be retrieved.

A missing GPU metric must not crash the entire agent.

---

# 10. NETWORK COLLECTION

Collect basic network information:

* hostname;
* local IP addresses;
* network interfaces;
* interface state;
* gateway when available;
* DNS configuration when available;
* basic connectivity state.

The agent should distinguish between:

```text
LOCAL NETWORK AVAILABLE
```

and:

```text
INTERNET AVAILABLE
```

These are not the same condition.

---

# 11. NETWORK DIAGNOSTICS

Implement safe diagnostic operations.

Examples:

### Gateway reachability

Determine whether the local gateway responds.

### Internet reachability

Test connectivity against configurable external targets.

### DNS resolution

Test whether a hostname can be resolved.

### Latency

Measure round-trip latency.

### Packet loss

When practical, calculate packet loss using a controlled number of probes.

### Diagnostic classification

The system should attempt to classify conditions such as:

```text
HEALTHY
DEGRADED
UNSTABLE
OFFLINE
UNKNOWN
```

Do not claim that the system can definitively identify the cause of every network problem.

The system should report evidence and possible causes.

Example:

```text
Status: DEGRADED

Evidence:
- Gateway reachable
- Internet reachable
- DNS resolution intermittent
- Packet loss detected

Possible causes:
- DNS instability
- ISP DNS issue
- Router configuration
- Local network instability
```

---

# 12. HEALTH ENGINE

Create a rule-based diagnostic engine.

The first version should NOT depend on an LLM.

The diagnostic engine must be deterministic.

Example rules:

```text
Disk usage > configurable threshold
    → DISK_SPACE_WARNING

Memory usage > configurable threshold
    → MEMORY_PRESSURE

CPU sustained above configurable threshold
    → HIGH_CPU_USAGE

Gateway unreachable
    → LOCAL_NETWORK_FAILURE

Internet unreachable while gateway reachable
    → INTERNET_CONNECTIVITY_FAILURE

DNS failure while internet connectivity exists
    → DNS_FAILURE
```

Thresholds must be configurable.

Do not hard-code every threshold.

---

# 13. DIAGNOSTIC RESULT MODEL

Create a structured diagnostic result.

Conceptually:

```json
{
  "timestamp": "...",
  "device_id": "...",
  "status": "DEGRADED",
  "checks": [],
  "alerts": [],
  "metrics": []
}
```

Every diagnostic event should contain enough information to understand:

* what was checked;
* when it was checked;
* what happened;
* what evidence was found;
* what status resulted.

---

# 14. DEVICE IDENTITY

Every agent installation must have a stable device identifier.

The identifier must NOT depend exclusively on the current IP address.

The device ID should remain stable across network changes.

Do not use sensitive hardware identifiers unnecessarily.

Document the identity strategy.

---

# 15. LOCAL STORAGE

The agent must maintain local state.

SQLite is preferred for version 1.

The local database should contain information such as:

```text
devices
diagnostic_runs
diagnostic_results
sync_queue
sync_attempts
```

The schema must be documented.

---

# 16. OFFLINE QUEUE

When cloud synchronization fails:

1. Do not lose the diagnostic event.
2. Store the event locally.
3. Mark it as pending.
4. Retry later.
5. Avoid infinite aggressive retries.
6. Use bounded retry behavior.
7. Record synchronization attempts.
8. Mark successful events as synchronized.

The implementation should use retry backoff.

Avoid creating a busy loop.

---

# 17. CLOUD API

The cloud backend should expose a REST API.

Initial conceptual endpoints:

```text
POST /v1/devices
POST /v1/telemetry
GET  /v1/devices
GET  /v1/devices/{device_id}
GET  /v1/devices/{device_id}/diagnostics
GET  /health
```

The exact endpoint structure may be refined during implementation.

Every endpoint must have:

* purpose;
* request schema;
* response schema;
* error behavior;
* authentication requirements;
* example request;
* example response.

---

# 18. API GATEWAY

Use Amazon API Gateway as the public API entry point.

API Gateway must be responsible for:

* HTTP routing;
* request handling;
* integration with Lambda;
* API-level controls where appropriate;
* access logging where appropriate.

Do not put business logic inside API Gateway.

Business logic belongs in Lambda/application code.

---

# 19. AWS LAMBDA

Lambda should contain backend application logic.

Separate responsibilities clearly.

Possible logical handlers:

```text
device_handler
telemetry_handler
diagnostic_handler
health_handler
```

Avoid creating excessive Lambda functions if it does not improve the architecture.

The architecture should prioritize maintainability and understandable boundaries.

---

# 20. DYNAMODB

Use DynamoDB for cloud-side persistence.

Store only information actually required by the cloud application.

Do not blindly upload every raw local system detail.

Potential entities:

```text
Device
Telemetry
DiagnosticEvent
```

Define:

* partition key;
* sort key where necessary;
* access patterns;
* indexes only when justified.

Document why each key exists.

The DynamoDB design must be based on application access patterns rather than relational-table thinking.

---

# 21. CLOUDWATCH

Use CloudWatch for:

* Lambda logs;
* application logs;
* errors;
* operational metrics where appropriate.

Important events should be observable.

Examples:

```text
TelemetryAccepted
TelemetryRejected
DeviceRegistered
SyncFailure
LambdaError
ValidationError
```

Do not log secrets.

Do not log unnecessary sensitive system information.

---

# 22. SECURITY

Security is a first-class requirement.

The project must include:

## Transport

Use HTTPS for cloud communication.

## Authentication

Implement a reasonable authentication mechanism for the API.

The authentication strategy must be documented.

Do not hard-code credentials.

## IAM

Use least privilege.

Avoid:

```text
AdministratorAccess
```

for application roles.

The Lambda execution role should have only the permissions necessary for its operations.

## Secrets

Never commit:

* AWS access keys;
* tokens;
* passwords;
* API keys;
* private credentials.

Use environment variables or appropriate secret/configuration mechanisms.

## Input validation

All cloud API input must be validated.

Reject malformed requests.

## Data minimization

Only send information required by the application.

The local agent should not upload arbitrary files or personal content.

---

# 23. PRIVACY

The agent is an infrastructure diagnostic tool.

It must NOT collect:

* browser history;
* passwords;
* private documents;
* message contents;
* personal files;
* keystrokes;
* screenshots by default;
* arbitrary user content.

The README must contain a clear privacy section explaining what the system collects and what it does not collect.

---

# 24. COST CONTROL

The project must be designed for extremely low AWS usage.

The implementation must avoid unnecessary:

* polling;
* high-frequency telemetry;
* large payloads;
* unnecessary database writes;
* unnecessary API requests;
* long-running compute;
* high-cardinality logging.

Provide a configurable telemetry interval.

Example:

```text
TELEMETRY_INTERVAL_SECONDS
```

The default development configuration should be conservative.

The README must include:

# Cost Considerations

Explain:

* which AWS services are used;
* why they are used;
* what creates costs;
* how development usage is minimized;
* how to shut down/remove infrastructure;
* what resources must be deleted when the experiment ends.

Do not assume that AWS resources are free.

---

# 25. CONFIGURATION

Configuration must not be scattered throughout the source code.

Use environment variables and/or a configuration file.

Example:

```text
API_BASE_URL
DEVICE_ID
TELEMETRY_INTERVAL
LOG_LEVEL
DATABASE_PATH
RETRY_LIMIT
RETRY_BACKOFF
```

Provide:

```text
.env.example
```

Never commit the actual `.env`.

---

# 26. ERROR HANDLING

The application must fail gracefully.

Examples:

If hardware collection fails:

```text
Continue with other collectors.
```

If DNS fails:

```text
Report DNS failure.
Do not crash the entire diagnostic run.
```

If AWS is unavailable:

```text
Persist telemetry locally.
Retry later.
```

If DynamoDB rejects a request:

```text
Log structured error.
Preserve local event.
```

Unexpected exceptions must be logged with enough context to diagnose the problem.

---

# 27. LOGGING

Use structured logging where practical.

Logs should contain information such as:

```text
timestamp
level
component
event
device_id
request_id
error
```

Avoid sensitive information.

Use appropriate log levels:

```text
DEBUG
INFO
WARNING
ERROR
```

---

# 28. TESTING STRATEGY

Testing is mandatory.

Create:

## Unit tests

Test:

* collectors;
* diagnostic rules;
* health classification;
* serializers;
* validators;
* retry logic;
* queue logic.

## Integration tests

Test:

```text
Agent
   ↓
API
   ↓
Lambda
   ↓
DynamoDB
```

where practical.

## Failure tests

Explicitly test:

* internet unavailable;
* DNS unavailable;
* API unavailable;
* malformed response;
* database failure;
* invalid telemetry;
* duplicate telemetry;
* retry exhaustion.

## Offline tests

The agent must demonstrate that diagnostics still work without cloud access.

---

# 29. DEMO MODE

Implement a demo mode that does not require real hardware anomalies.

Example:

```bash
diagnostic-agent demo
```

The demo should generate deterministic simulated scenarios such as:

```text
HEALTHY
DEGRADED_NETWORK
LOW_DISK
HIGH_MEMORY
DNS_FAILURE
OFFLINE_MODE
```

This allows the project to be demonstrated without intentionally damaging a computer or creating real failures.

---

# 30. CLI

Provide a command-line interface.

Possible commands:

```bash
diagnostic-agent scan
diagnostic-agent network
diagnostic-agent hardware
diagnostic-agent health
diagnostic-agent sync
diagnostic-agent status
diagnostic-agent queue
diagnostic-agent demo
```

The exact CLI structure may be improved if necessary.

Each command must have help documentation.

Example:

```bash
diagnostic-agent --help
```

---

# 31. LOCAL REPORT

The agent should be capable of generating a human-readable report.

Example:

```text
========================================
LOCAL DIAGNOSTIC REPORT
========================================

Device:
PC-001

System:
Windows 11
Uptime: 2d 04h

CPU:
Usage: 32%

Memory:
Usage: 61%

Storage:
C:
Usage: 87%

Network:
Gateway: OK
Internet: OK
DNS: OK
Latency: 18ms

Overall health:
HEALTHY
```

The report should clearly distinguish:

* observed facts;
* diagnostic rules;
* recommendations.

---

# 32. CLOUD DATA MODEL

Document the DynamoDB data model.

Before implementation, create a section in the documentation explaining:

```text
What data is stored?
Why is it stored?
How is it queried?
What is the partition key?
What is the sort key?
What is the expected access pattern?
```

Do not simply create tables without explaining their purpose.

---

# 33. INFRASTRUCTURE AS CODE

Prefer infrastructure as code.

Choose an appropriate approach for the project.

Possible options:

* AWS SAM;
* AWS CDK;
* Terraform.

Select ONE primary approach.

The choice must be documented in an Architecture Decision Record.

Infrastructure must be reproducible.

Avoid manually creating production infrastructure through the AWS Console unless necessary for experimentation.

---

# 34. LOCAL DEVELOPMENT

The project must be runnable locally.

Provide:

```text
README.md
.env.example
requirements.txt
pyproject.toml
Makefile or task runner if useful
```

Provide commands such as:

```bash
python -m venv .venv
pip install -r requirements.txt
pytest
python -m agent
```

The exact commands may differ according to the final implementation.

---

# 35. REPOSITORY STRUCTURE

Create a professional repository.

Suggested:

```text
local-to-cloud-diagnostic-gateway/
│
├── README.md
├── LICENSE
├── .gitignore
├── .env.example
├── pyproject.toml
│
├── docs/
│   ├── architecture.md
│   ├── security.md
│   ├── cost.md
│   ├── api.md
│   ├── data-model.md
│   ├── troubleshooting.md
│   └── decisions/
│       ├── ADR-001-local-first.md
│       ├── ADR-002-serverless-backend.md
│       └── ADR-003-database-choice.md
│
├── diagrams/
│   ├── architecture.mmd
│   └── data-flow.mmd
│
├── src/
│   ├── agent/
│   ├── shared/
│   └── cloud/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
├── infrastructure/
│
└── scripts/
```

Adjust the structure if the implementation requires it.

---

# 36. ARCHITECTURE DECISION RECORDS

Create ADRs for important decisions.

At minimum:

## ADR-001

Why the system uses a local-first architecture.

## ADR-002

Why AWS serverless services are used.

## ADR-003

Why DynamoDB was selected.

## ADR-004

Why SQLite is used locally.

## ADR-005

Why the system uses an offline synchronization queue.

Each ADR must explain:

```text
Context
Decision
Alternatives
Consequences
```

This documentation is mandatory because the project must be understandable by its author during a technical interview.

---

# 37. THREAT MODEL

Create a basic threat model.

Consider:

* stolen API credentials;
* malicious telemetry;
* unauthorized API requests;
* replayed requests;
* malformed payloads;
* compromised local agent;
* excessive API requests;
* leaked logs;
* exposed secrets.

For each threat:

```text
Threat
Impact
Mitigation
Residual risk
```

Do not pretend the system is perfectly secure.

---

# 38. OBSERVABILITY MODEL

Document:

```text
What can fail?
How will we know?
Where will the failure appear?
```

Examples:

```text
Agent failure
→ local logs

Synchronization failure
→ local queue + logs

Lambda failure
→ CloudWatch

Invalid request
→ API response + CloudWatch

DynamoDB failure
→ Lambda logs + preserved local event
```

---

# 39. API DOCUMENTATION

Create API documentation.

For each endpoint include:

```text
Method
Path
Purpose
Authentication
Request
Response
Errors
Example
```

Provide example JSON.

The API contract must be versioned:

```text
/v1/...
```

---

# 40. FAILURE SCENARIOS

The final documentation must contain a failure matrix.

Example:

| Failure              | Expected behavior               |
| -------------------- | ------------------------------- |
| Internet unavailable | Continue locally                |
| DNS unavailable      | Report DNS failure              |
| API unavailable      | Queue telemetry                 |
| Lambda error         | Preserve local event            |
| DynamoDB unavailable | Retry / preserve event          |
| Invalid payload      | Reject request                  |
| Duplicate event      | Avoid unintended duplication    |
| Agent exception      | Log and continue where possible |

---

# 41. IDEMPOTENCY

Cloud ingestion should consider duplicate events.

The same telemetry event may be sent more than once because of retries.

Design the system so that retrying a request does not unintentionally create unlimited duplicate records.

Define an event identifier.

Example:

```text
event_id
```

The event ID should be generated before synchronization.

---

# 42. SYNCHRONIZATION STATE MACHINE

Document and implement synchronization states.

Possible states:

```text
PENDING
SYNCING
SYNCED
FAILED
DEAD_LETTER
```

The exact state model may be simplified if appropriate.

The state transitions must be documented.

Example:

```text
PENDING
   ↓
SYNCING
   ↓
SUCCESS
   ↓
SYNCED
```

Failure:

```text
SYNCING
   ↓
FAILED
   ↓
RETRY
```

After configured retries:

```text
FAILED
   ↓
DEAD_LETTER
```

---

# 43. DATA FLOW DOCUMENTATION

Create a complete data-flow diagram.

Show:

```text
Hardware
   ↓
Collector
   ↓
Diagnostic Engine
   ↓
Local Database
   ↓
Sync Queue
   ↓
HTTPS
   ↓
API Gateway
   ↓
Lambda
   ↓
Validation
   ↓
DynamoDB
   ↓
CloudWatch
```

Explain what data exists at each stage.

---

# 44. SECURITY BOUNDARIES

Document security boundaries.

At minimum:

```text
LOCAL TRUST DOMAIN
        │
        │ HTTPS
        ▼
PUBLIC API
        │
        ▼
AWS APPLICATION
        │
        ▼
DATABASE
```

Explain which components are trusted and which are not.

---

# 45. PORTFOLIO REQUIREMENTS

The project must be visually and technically presentable on GitHub.

README must include:

1. Project title.
2. Project description.
3. Problem statement.
4. Why this project exists.
5. Architecture diagram.
6. Technology stack.
7. Features.
8. Installation.
9. Local execution.
10. AWS deployment.
11. API documentation.
12. Security.
13. Cost considerations.
14. Testing.
15. Failure handling.
16. Architecture decisions.
17. Limitations.
18. Future improvements.
19. Screenshots/examples where appropriate.
20. Author section.

Do not use generic portfolio language.

Explain the actual engineering decisions made in this project.

---

# 46. AUTHOR TECHNICAL UNDERSTANDING

The generated documentation must make the architecture understandable to a developer who did not build the project.

For every major AWS component, explain:

```text
What is it?
Why does this project use it?
What problem does it solve?
What happens if it fails?
What does it cost?
What permissions does it need?
```

For every major Python component, explain:

```text
What is it?
What does it collect or process?
What does it depend on?
What happens if it fails?
```

This documentation is especially important because the project will be presented as a portfolio project by its author.

---

# 47. AI USAGE POLICY

AI-assisted development is allowed and expected.

However:

* AI-generated code must be reviewed.
* Do not blindly accept generated code.
* Do not leave unexplained generated abstractions.
* Do not introduce dependencies without justification.
* Do not generate unnecessary complexity.
* Do not hide implementation decisions.
* Do not claim manually implemented functionality that was generated automatically.

The final README may include a short section explaining that AI tools were used as development assistants.

---

# 48. CODE QUALITY

The implementation must prioritize:

* readability;
* modularity;
* type hints;
* clear function names;
* clear module boundaries;
* meaningful error handling;
* testability;
* small cohesive functions;
* minimal unnecessary abstraction.

Avoid:

* giant files;
* giant functions;
* duplicated logic;
* magic numbers;
* hard-coded credentials;
* unnecessary frameworks;
* unnecessary dependencies.

---

# 49. DEPENDENCY POLICY

Before adding a dependency, determine whether it is actually necessary.

Prefer standard library functionality when practical.

If a third-party dependency is required:

1. Explain why.
2. Pin or constrain the version appropriately.
3. Document its purpose.

---

# 50. DEVELOPMENT PHASES

Implement the project in phases.

## Phase 0 — Project foundation

Create:

* repository;
* Python project;
* configuration;
* logging;
* test framework;
* basic CLI.

Do not implement everything at once.

## Phase 1 — Local collectors

Implement:

* CPU;
* memory;
* storage;
* OS;
* hardware;
* network.

## Phase 2 — Diagnostic engine

Implement:

* health checks;
* rules;
* thresholds;
* diagnostic classification.

## Phase 3 — Local persistence

Implement:

* SQLite;
* diagnostic history;
* event IDs.

## Phase 4 — Offline queue

Implement:

* pending events;
* retry;
* synchronization states;
* backoff.

## Phase 5 — Cloud API

Implement:

* API Gateway;
* Lambda;
* validation;
* health endpoint.

## Phase 6 — Cloud persistence

Implement:

* DynamoDB;
* access patterns;
* idempotency.

## Phase 7 — Observability

Implement:

* CloudWatch logs;
* structured logging;
* operational metrics where appropriate.

## Phase 8 — Security

Implement:

* authentication;
* IAM;
* least privilege;
* secret handling;
* validation.

## Phase 9 — Testing

Implement:

* unit tests;
* integration tests;
* failure tests;
* offline tests.

## Phase 10 — Documentation

Create:

* architecture documentation;
* ADRs;
* API documentation;
* threat model;
* cost analysis;
* troubleshooting;
* diagrams.

## Phase 11 — Portfolio polish

Improve:

* README;
* screenshots;
* architecture diagram;
* examples;
* demo mode;
* installation instructions.

---

# 51. DEFINITION OF DONE

The project is considered complete only when:

* [ ] Local agent starts successfully.
* [ ] Hardware information can be collected.
* [ ] OS information can be collected.
* [ ] Storage information can be collected.
* [ ] Network diagnostics work.
* [ ] Diagnostic rules work.
* [ ] Local data is persisted.
* [ ] Offline mode works.
* [ ] Synchronization queue works.
* [ ] Cloud API works.
* [ ] Lambda functions work.
* [ ] DynamoDB persistence works.
* [ ] Duplicate events are handled.
* [ ] Authentication exists.
* [ ] IAM permissions follow least privilege.
* [ ] Secrets are not committed.
* [ ] CloudWatch logs exist.
* [ ] Unit tests exist.
* [ ] Integration tests exist where practical.
* [ ] Failure scenarios are tested.
* [ ] Demo mode works.
* [ ] API documentation exists.
* [ ] Architecture documentation exists.
* [ ] ADRs exist.
* [ ] Threat model exists.
* [ ] Cost documentation exists.
* [ ] Deployment instructions exist.
* [ ] Cleanup instructions exist.
* [ ] README is portfolio-ready.

---

# 52. FINAL IMPLEMENTATION INSTRUCTION

You are acting as a senior software/cloud engineering implementation agent.

Read this entire specification before modifying the repository.

Do not immediately start writing arbitrary code.

First:

1. Analyze the requirements.
2. Inspect the existing repository.
3. Identify constraints.
4. Propose the implementation plan.
5. Identify ambiguities.
6. Define the architecture.
7. Define the repository structure.
8. Define the implementation phases.

Then implement the application phase by phase.

Do not skip requirements silently.

If a requirement conflicts with another requirement, identify the conflict and choose the safer and simpler architectural solution.

Document important decisions.

Do not create fake integrations.

Do not create placeholder functions presented as complete functionality.

Do not use mock data as a substitute for a required real implementation except in explicit demo/test modes.

Do not introduce AWS services without architectural justification.

Do not expose secrets.

Do not implement invasive or destructive diagnostics.

Keep the system cost-conscious.

The application must remain useful locally when AWS or the internet is unavailable.

---

# 53. REQUIRED FINAL DELIVERABLE

At the end of implementation, produce a final engineering report containing:

## Architecture Summary

Explain the final architecture.

## Components

List every important component and its responsibility.

## Data Flow

Explain how information travels from the local computer to AWS.

## Security

Explain authentication, authorization, secrets and trust boundaries.

## Reliability

Explain offline operation, retries and synchronization.

## AWS

Explain every AWS service used and why.

## Cost

Explain the main cost drivers and how development costs are minimized.

## Testing

Report the tests implemented and their results.

## Known Limitations

Be honest about limitations.

## Future Improvements

List realistic next steps.

## Developer Study Guide

Create a section called:

# What the developer must understand

List the concepts the project author should study before presenting the project.

At minimum:

* Python modules;
* classes and functions;
* type hints;
* exceptions;
* HTTP;
* REST;
* JSON;
* API Gateway;
* Lambda;
* DynamoDB;
* IAM;
* CloudWatch;
* authentication;
* authorization;
* SQLite;
* queues;
* retries;
* idempotency;
* observability;
* edge computing;
* serverless architecture;
* infrastructure as code;
* network diagnostics;
* DNS;
* TCP/IP;
* HTTP status codes;
* HTTPS;
* AWS cost management.

For each topic, explain briefly:

```text
What it is
Why this project uses it
Where it appears in the code
```

The objective is not merely to finish the application.

The objective is to produce a technically credible system that its author can understand, explain, maintain, modify and defend in a technical interview.

---

# 54. FINAL RULE

Build the system as if another engineer will inherit the repository tomorrow.

Build it so that the author can study it afterward.

Build it so that the architecture tells a coherent engineering story.

Build it with real implementations, realistic failure handling and explicit trade-offs.

Do not optimize for the number of files created.

Optimize for:

**clarity + architecture + reliability + security + learning value + portfolio quality.**
