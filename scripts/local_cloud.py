"""Developer tool: run the cloud backend locally against moto (NOT AWS).

Starts an in-process moto mock for DynamoDB and SSM, creates the single table
and the two SecureString API keys, points the handlers at them through
environment variables, and serves the real Lambda handlers over a local HTTP
server (``tests/support/local_api.py``). This never contacts AWS; it is a
convenience for manual testing and demos.

Run with the dev virtualenv interpreter:

    .venv\\Scripts\\python.exe scripts/local_cloud.py

Then, in another shell:

    curl http://127.0.0.1:<port>/health
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(_REPO_ROOT / "tests"))

_RULE = "=" * 60
BANNER = f"{_RULE}\n  LOCAL EMULATION - NOT AWS (moto-backed DynamoDB + SSM)\n{_RULE}"

_TABLE_NAME = "diagnostic-gateway-local-diagnostics"
_INGEST_PARAM = "/diagnostic-gateway/local/ingest-api-key"
_READ_PARAM = "/diagnostic-gateway/local/read-api-key"
_INGEST_KEY = "local-ingest-key"  # noqa: S105 - dev-only fixed key.
_READ_KEY = "local-read-key"  # noqa: S105 - dev-only fixed key.


def _create_table(dynamodb: object) -> None:
    dynamodb.create_table(  # type: ignore[attr-defined]
        TableName=_TABLE_NAME,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI1PK", "AttributeType": "S"},
            {"AttributeName": "GSI1SK", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "GSI1",
                "KeySchema": [
                    {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    )


def main() -> int:
    # Fake credentials so moto never reaches a real account.
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    os.environ["TABLE_NAME"] = _TABLE_NAME
    os.environ["INGEST_KEY_PARAMETER"] = _INGEST_PARAM
    os.environ["READ_KEY_PARAMETER"] = _READ_PARAM
    os.environ["DIAGNOSTIC_RETENTION_DAYS"] = "30"

    try:
        import boto3
        from moto import mock_aws
    except ImportError:
        print("This dev tool needs the dev dependencies (moto, boto3).")
        return 2

    print(BANNER)

    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_table(ddb)
        ssm = boto3.client("ssm", region_name="us-east-1")
        ssm.put_parameter(Name=_INGEST_PARAM, Value=_INGEST_KEY, Type="SecureString")
        ssm.put_parameter(Name=_READ_PARAM, Value=_READ_KEY, Type="SecureString")

        # Import only after env + mocks are in place so the lru_cache picks the
        # mocked resources.
        from cloud.repository import get_table
        from support.local_api import LocalApiServer

        get_table.cache_clear()

        with LocalApiServer() as server:
            print(f"Serving on {server.base_url} (Ctrl+C to stop)")
            print(f"  ingest key: {_INGEST_KEY}")
            print(f"  read key:   {_READ_KEY}")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\nStopping local emulation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
