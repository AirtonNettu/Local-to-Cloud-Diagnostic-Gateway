"""EMF metric line shape (design B.14): namespace, dimensions, no device_id."""

from __future__ import annotations

import json

from cloud import metrics


def test_emf_line_shape() -> None:
    line = metrics.build_emf_line(
        metrics.TELEMETRY_ACCEPTED,
        service="diagnostic-gateway",
        function="telemetry",
        timestamp_ms=1_700_000_000_000,
    )
    doc = json.loads(line)
    cw = doc["_aws"]["CloudWatchMetrics"][0]
    assert doc["_aws"]["Timestamp"] == 1_700_000_000_000
    assert cw["Namespace"] == metrics.NAMESPACE
    assert cw["Dimensions"] == [["Service", "Function"]]
    assert cw["Metrics"] == [{"Name": "TelemetryAccepted", "Unit": "Count"}]
    assert doc["Service"] == "diagnostic-gateway"
    assert doc["Function"] == "telemetry"
    assert doc["TelemetryAccepted"] == 1


def test_device_id_is_never_a_dimension() -> None:
    line = metrics.build_emf_line(
        metrics.DEVICE_REGISTERED, service="svc", function="device"
    )
    doc = json.loads(line)
    dims = doc["_aws"]["CloudWatchMetrics"][0]["Dimensions"][0]
    assert "device_id" not in dims
    assert "device_id" not in doc


def test_all_eight_metric_names_defined() -> None:
    names = {
        metrics.DEVICE_REGISTERED,
        metrics.TELEMETRY_ACCEPTED,
        metrics.TELEMETRY_DUPLICATE,
        metrics.TELEMETRY_REJECTED,
        metrics.VALIDATION_ERROR,
        metrics.AUTH_FAILURE,
        metrics.DYNAMODB_ERROR,
        metrics.LAMBDA_ERROR,
    }
    assert len(names) == 8


def test_emit_metric_prints_a_single_line(capsys) -> None:
    metrics.emit_metric(metrics.AUTH_FAILURE, service="svc", function="device")
    out = capsys.readouterr().out.strip()
    assert out.count("\n") == 0
    json.loads(out)  # valid JSON
