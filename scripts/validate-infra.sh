#!/usr/bin/env bash
# Validate the SAM template offline. Never touches an AWS account.
#
# Runs cfn-lint always. Runs `sam validate --lint` only if the SAM CLI is on
# PATH; it is skipped with an explicit note otherwise.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
template="${repo_root}/infrastructure/template.yaml"

echo "Running cfn-lint on ${template}"
if [ -x "${repo_root}/.venv/bin/cfn-lint" ]; then
    "${repo_root}/.venv/bin/cfn-lint" "${template}"
else
    cfn-lint "${template}"
fi

if command -v sam >/dev/null 2>&1; then
    echo "Running sam validate --lint"
    sam validate --lint -t "${template}"
else
    echo "SKIP: sam validate - the SAM CLI is not installed on this machine."
fi

echo "Offline infrastructure validation complete."
