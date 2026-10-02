"""CloudWatch EMF metric emission (design B.14 / B.15).

``emit_metric`` prints one Embedded Metric Format JSON line to stdout, which
Lambda ships to CloudWatch Logs and CloudWatch turns into a custom metric. The
namespace is ``DiagnosticGateway`` and the single dimension set is
``[["Service", "Function"]]``. The device id is deliberately never a dimension
(it is high cardinality, §24) though it may appear as a plain log property.
"""

from __future__ import annotations

import json
import time

__all__ = [
    "emit_metric",
    "NAMESPACE",
    "DEVICE_REGISTERED",
    "TELEMETRY_ACCEPTED",
    "TELEMETRY_DUPLICATE",
    "TELEMETRY_REJECTED",
    "VALIDATION_ERROR",
    "AUTH_FAILURE",
    "DYNAMODB_ERROR",
    "LAMBDA_ERROR",
]

NAMESPACE = "DiagnosticGateway"

# The eight metric names (design B.14). device_id is never a dimension.
DEVICE_REGISTERED = "DeviceRegistered"
TELEMETRY_ACCEPTED = "TelemetryAccepted"
TELEMETRY_DUPLICATE = "TelemetryDuplicate"
TELEMETRY_REJECTED = "TelemetryRejected"
VALIDATION_ERROR = "ValidationError"
AUTH_FAILURE = "AuthFailure"
DYNAMODB_ERROR = "DynamoDBError"
LAMBDA_ERROR = "LambdaError"


def emit_metric(
    name: str,
    *,
    service: str,
    function: str,
    value: int | float = 1,
    unit: str = "Count",
) -> None:
    """Print one EMF line declaring ``name`` under the Service/Function dims.

    ``service`` and ``function`` fill the ``[["Service", "Function"]]`` dimension
    set. ``value`` defaults to 1 (a count of one occurrence).
    """
    line = build_emf_line(
        name, service=service, function=function, value=value, unit=unit
    )
    print(line)  # noqa: T201 - EMF is emitted to stdout for CloudWatch.


def build_emf_line(
    name: str,
    *,
    service: str,
    function: str,
    value: int | float = 1,
    unit: str = "Count",
    timestamp_ms: int | None = None,
) -> str:
    """Return the EMF JSON line for a metric (extracted so tests can assert it)."""
    ts = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)
    document = {
        "_aws": {
            "Timestamp": ts,
            "CloudWatchMetrics": [
                {
                    "Namespace": NAMESPACE,
                    "Dimensions": [["Service", "Function"]],
                    "Metrics": [{"Name": name, "Unit": unit}],
                }
            ],
        },
        "Service": service,
        "Function": function,
        name: value,
    }
    return json.dumps(document, separators=(",", ":"))
