# Cost

> Language: English · [Português (Brasil)](cost.pt-BR.md)

The backend is serverless and pay-per-use, so idle cost is near zero. This
document lists the services, the cost drivers, how the design minimizes cost,
and how to tear everything down.

## Services and cost model

| Service | Billed on |
|---|---|
| HTTP API Gateway | per million requests |
| Lambda | per request + GB-seconds (128 MB, `arm64`) |
| DynamoDB | on-demand read/write request units + stored bytes |
| CloudWatch Logs | ingested GB + stored GB (14-day retention) |
| CloudWatch custom metrics (EMF) | per metric name × dimension per month |
| SSM Parameter Store | standard SecureStrings are free |

## Cost drivers

- **Request volume**: with hourly telemetry per device the request count is
  tiny; cost scales with the number of devices and scan frequency.
- **Log ingestion**: structured logs are small and retention is 14 days.
- **DynamoDB storage**: events expire via TTL (default 30 days), capping growth.
- **Custom metrics**: see the note below.

## EMF custom-metric billing note

CloudWatch custom metrics are billed **per metric name × dimension combination
per month**, and only in the hours a metric actually emits a data point (there
is no charge for a metric name that is silent all month). This project defines
eight metric names (`DeviceRegistered`, `TelemetryAccepted`,
`TelemetryDuplicate`, `TelemetryRejected`, `ValidationError`, `AuthFailure`,
`DynamoDBError`, `LambdaError`) under one dimension set `[["Service",
"Function"]]`. Because the `Function` dimension value varies by emitting
function, the realistic count is roughly **10–12 billable custom metrics** in
the months the backend is active, and zero in months with no traffic. Keeping
`device_id` out of the dimensions is deliberate: a high-cardinality dimension
would multiply this cost dramatically.

## Minimization

- On-demand DynamoDB (no provisioned capacity to pay for while idle).
- Short-timeout, 128 MB `arm64` Lambda functions.
- 14-day log retention and TTL on diagnostic events.
- A low, fixed set of EMF metric names with a single low-cardinality dimension.
- API Gateway throttling bounds a runaway or hostile caller.
- Point-in-time recovery is off by default (a documented trade-off).

## Teardown

Deleting the SAM/CloudFormation stack removes everything billable. The template
sets `DeletionPolicy: Delete` on the table and all log groups, so a stack delete
leaves nothing behind. Use `scripts/teardown.{ps1,sh}`. The SSM SecureString
parameters are created outside the stack and should be deleted separately when
no longer needed.
