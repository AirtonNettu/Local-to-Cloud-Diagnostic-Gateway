"""Offline assertions on the SAM template (design B.16, acceptance criteria).

The template is loaded with ``cfnlint.decode.decode_str`` (not a YAML loader) so
intrinsic functions decode the way cfn-lint sees them. The tests assert the
least-privilege IAM shape, DynamoDB settings, log retention, the per-function
environment superset of each handler's ``REQUIRED_ENV``, the exact ``Fn::Sub``
ARN strings, the ``AllowedPattern`` on the key names and that the routes match
the local test router so the two cannot drift.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cfnlint.decode import decode_str

from cloud.handlers import device, diagnostic, health, telemetry
from tests.support.local_api import ROUTES

_TEMPLATE = Path(__file__).resolve().parents[2] / "infrastructure" / "template.yaml"

_FUNCTION_HANDLERS = {
    "HealthFunction": health,
    "DeviceFunction": device,
    "TelemetryFunction": telemetry,
    "DiagnosticFunction": diagnostic,
}
_FUNCTION_ROLE = {
    "HealthFunction": "HealthRole",
    "DeviceFunction": "DeviceRole",
    "TelemetryFunction": "TelemetryRole",
    "DiagnosticFunction": "DiagnosticRole",
}


def _load() -> dict[str, Any]:
    template, matches = decode_str(_TEMPLATE.read_text(encoding="utf-8"))
    assert not matches, f"template failed to decode: {matches}"
    return template


def _resources() -> dict[str, Any]:
    return _load()["Resources"]


def _statements(role: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for policy in role["Properties"]["Policies"]:
        out.extend(policy["PolicyDocument"]["Statement"])
    return out


def test_transform_is_serverless() -> None:
    assert _load()["Transform"] == "AWS::Serverless-2016-10-31"


def test_one_explicit_role_per_function_no_managed_policies() -> None:
    resources = _resources()
    for function, role_name in _FUNCTION_ROLE.items():
        assert resources[function]["Properties"]["Role"] == {
            "Fn::GetAtt": [role_name, "Arn"]
        }
        role = resources[role_name]
        assert role["Type"] == "AWS::IAM::Role"
        # No managed policies: only inline Policies are allowed.
        assert "ManagedPolicyArns" not in role["Properties"]


def test_no_iam_wildcard_actions_or_resources() -> None:
    resources = _resources()
    for role_name in _FUNCTION_ROLE.values():
        for statement in _statements(resources[role_name]):
            actions = statement["Action"]
            actions = actions if isinstance(actions, list) else [actions]
            for action in actions:
                assert "*" not in action, f"wildcard action in {role_name}: {action}"
            resource = statement["Resource"]
            resources_list = resource if isinstance(resource, list) else [resource]
            for item in resources_list:
                assert item != "*"


def test_table_is_pay_per_request_with_ttl() -> None:
    table = _resources()["DiagnosticsTable"]["Properties"]
    assert table["BillingMode"] == "PAY_PER_REQUEST"
    ttl = table["TimeToLiveSpecification"]
    assert ttl["AttributeName"] == "expires_at"
    assert ttl["Enabled"] is True
    assert _resources()["DiagnosticsTable"]["DeletionPolicy"] == "Delete"


def test_log_groups_use_retention_parameter() -> None:
    resources = _resources()
    log_groups = [
        name
        for name, body in resources.items()
        if body["Type"] == "AWS::Logs::LogGroup"
    ]
    assert len(log_groups) == 5  # four functions + access log
    for name in log_groups:
        retention = resources[name]["Properties"]["RetentionInDays"]
        assert retention == {"Ref": "LogRetentionDays"}


def test_log_retention_default_is_14() -> None:
    assert _load()["Parameters"]["LogRetentionDays"]["Default"] == 14


def test_key_parameters_have_allowed_pattern() -> None:
    params = _load()["Parameters"]
    for name in ("IngestKeyParameterName", "ReadKeyParameterName"):
        assert params[name]["AllowedPattern"] == "^/[A-Za-z0-9/_.-]{1,1000}$"


def test_merged_env_superset_of_required_env() -> None:
    load = _load()
    globals_env = (
        load["Globals"]["Function"]["Environment"]["Variables"]
    )
    resources = load["Resources"]
    for function, module in _FUNCTION_HANDLERS.items():
        own = (
            resources[function]["Properties"]
            .get("Environment", {})
            .get("Variables", {})
        )
        merged = set(globals_env) | set(own)
        assert set(module.REQUIRED_ENV).issubset(merged), function


def test_table_name_absent_from_health() -> None:
    load = _load()
    globals_env = load["Globals"]["Function"]["Environment"]["Variables"]
    health_env = (
        load["Resources"]["HealthFunction"]["Properties"]
        .get("Environment", {})
        .get("Variables", {})
    )
    assert "TABLE_NAME" not in globals_env
    assert "TABLE_NAME" not in health_env


def test_exact_fn_sub_arn_strings() -> None:
    resources = _resources()
    ingest_arn = (
        "arn:${AWS::Partition}:ssm:${AWS::Region}:${AWS::AccountId}:"
        "parameter${IngestKeyParameterName}"
    )
    read_arn = (
        "arn:${AWS::Partition}:ssm:${AWS::Region}:${AWS::AccountId}:"
        "parameter${ReadKeyParameterName}"
    )
    device_statements = _statements(resources["DeviceRole"])
    ssm_resources = [
        r
        for stmt in device_statements
        if "ssm:GetParameters" in _as_list(stmt["Action"])
        for r in _as_list(stmt["Resource"])
    ]
    assert {"Fn::Sub": ingest_arn} in ssm_resources
    assert {"Fn::Sub": read_arn} in ssm_resources

    log_arn = (
        "arn:${AWS::Partition}:logs:${AWS::Region}:${AWS::AccountId}:"
        "log-group:/aws/lambda/${AWS::StackName}-device:*"
    )
    log_resources = [
        r
        for stmt in device_statements
        if "logs:PutLogEvents" in _as_list(stmt["Action"])
        for r in _as_list(stmt["Resource"])
    ]
    assert {"Fn::Sub": log_arn} in log_resources


def test_device_role_grants_gsi_index() -> None:
    statements = _statements(_resources()["DeviceRole"])
    ddb = [
        r
        for stmt in statements
        if "dynamodb:Query" in _as_list(stmt["Action"])
        for r in _as_list(stmt["Resource"])
    ]
    assert {"Fn::Sub": "${DiagnosticsTable.Arn}/index/GSI1"} in ddb


def test_routes_match_local_router() -> None:
    """Each HttpApi event's method+path must match the local router table."""
    resources = _resources()
    template_routes: set[tuple[str, str]] = set()
    for function in _FUNCTION_HANDLERS:
        events = resources[function]["Properties"].get("Events", {})
        for event in events.values():
            props = event["Properties"]
            template_routes.add((props["Method"], props["Path"]))
    router_routes = {(route.method, route.path) for route in ROUTES}
    assert template_routes == router_routes


def test_outputs_present() -> None:
    outputs = _load()["Outputs"]
    assert set(outputs) == {"ApiBaseUrl", "TableName", "IngestKeyParameterName"}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]
