#!/usr/bin/env bash
# Tear down the diagnostic-gateway stack and its SSM key parameters.
# REQUIRES the AWS and SAM CLIs. This repository never runs this against AWS.
set -euo pipefail

stack_name="${1:-diagnostic-gateway-dev}"
stage="${2:-dev}"
force="${FORCE:-}"
ingest_param="/diagnostic-gateway/${stage}/ingest-api-key"
read_param="/diagnostic-gateway/${stage}/read-api-key"

for tool in aws sam; do
    command -v "$tool" >/dev/null 2>&1 || { echo "$tool CLI is required." >&2; exit 1; }
done

if [ "$force" != "1" ]; then
    read -r -p "Type the stack name '${stack_name}' to confirm deletion: " typed
    [ "$typed" = "$stack_name" ] || { echo "Aborted."; exit 0; }
fi

sam delete --stack-name "$stack_name" --no-prompts
aws ssm delete-parameters --names "$ingest_param" "$read_param" >/dev/null

echo "Stack and key parameters deleted."
echo "The SAM managed bucket/stack (aws-sam-cli-managed-default) from --resolve-s3 remains."
echo "To remove it, empty then delete the bucket, then delete the stack:"
echo "  aws s3 rm s3://<managed-bucket> --recursive"
echo "  aws cloudformation delete-stack --stack-name aws-sam-cli-managed-default"
