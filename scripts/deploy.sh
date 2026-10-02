#!/usr/bin/env bash
# Deploy the diagnostic-gateway stack. REQUIRES the AWS and SAM CLIs and real
# AWS credentials. This repository is never deployed; the script is provided for
# completeness and documentation.
set -euo pipefail

stack_name="${1:-diagnostic-gateway-dev}"
stage="${2:-dev}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
template="${repo_root}/infrastructure/template.yaml"
ingest_param="/diagnostic-gateway/${stage}/ingest-api-key"
read_param="/diagnostic-gateway/${stage}/read-api-key"

for tool in aws sam; do
    command -v "$tool" >/dev/null 2>&1 || { echo "$tool CLI is required." >&2; exit 1; }
done

account="$(aws sts get-caller-identity --query Account --output text)"
region="${AWS_DEFAULT_REGION:-$(aws configure get region)}"
echo "About to deploy '${stack_name}' to account ${account} in region ${region}."
read -r -p "Type 'yes' to continue: " confirm
[ "$confirm" = "yes" ] || { echo "Aborted."; exit 0; }

create_key_if_absent() {
    local name="$1"
    if aws ssm get-parameter --name "$name" >/dev/null 2>&1; then
        echo "SSM parameter ${name} already exists; leaving it unchanged."
        return
    fi
    local value
    value="$("${repo_root}/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(48))')"
    aws ssm put-parameter --name "$name" --type SecureString --value "$value" >/dev/null
    echo "Created SSM SecureString ${name} (value not displayed)."
}

create_key_if_absent "$ingest_param"
create_key_if_absent "$read_param"

sam build -t "$template"
sam deploy \
    --stack-name "$stack_name" \
    --capabilities CAPABILITY_IAM \
    --resolve-s3 \
    --no-fail-on-empty-changeset \
    --parameter-overrides "Stage=${stage}" "IngestKeyParameterName=${ingest_param}" "ReadKeyParameterName=${read_param}"

api_url="$(aws cloudformation describe-stacks --stack-name "$stack_name" \
    --query "Stacks[0].Outputs[?OutputKey=='ApiBaseUrl'].OutputValue" --output text)"
echo "ApiBaseUrl: ${api_url}"
echo "Read the ingest key into your local .env with:"
echo "  aws ssm get-parameter --name ${ingest_param} --with-decryption --query Parameter.Value --output text"
