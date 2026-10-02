# Deploy the diagnostic-gateway stack. REQUIRES the AWS and SAM CLIs and real
# AWS credentials. This repository is never deployed from CI or the dev machine;
# the script is provided for completeness and documentation.
#
# Steps: verify CLIs and identity, confirm account/region, create the two
# SecureString SSM parameters only if absent (values never echoed), sam build,
# sam deploy, then print the API base URL.
param(
    [string]$StackName = "diagnostic-gateway-dev",
    [string]$Stage = "dev",
    [string]$Region = $env:AWS_DEFAULT_REGION
)
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$template = Join-Path $repoRoot "infrastructure/template.yaml"
$ingestParam = "/diagnostic-gateway/$Stage/ingest-api-key"
$readParam = "/diagnostic-gateway/$Stage/read-api-key"

foreach ($tool in @("aws", "sam")) {
    if ($null -eq (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "$tool CLI is required but not found on PATH."
    }
}

$identity = aws sts get-caller-identity --output json | ConvertFrom-Json
if (-not $Region) { $Region = aws configure get region }
Write-Host "About to deploy '$StackName' to account $($identity.Account) in region $Region."
$confirm = Read-Host "Type 'yes' to continue"
if ($confirm -ne "yes") { Write-Host "Aborted."; return }

function New-KeyParameterIfAbsent([string]$name) {
    $exists = $true
    try { aws ssm get-parameter --name $name --output json | Out-Null }
    catch { $exists = $false }
    if ($exists) {
        Write-Host "SSM parameter $name already exists; leaving it unchanged."
        return
    }
    $value = & (Join-Path $repoRoot ".venv/Scripts/python.exe") -c "import secrets; print(secrets.token_urlsafe(48))"
    aws ssm put-parameter --name $name --type SecureString --value $value | Out-Null
    Write-Host "Created SSM SecureString $name (value not displayed)."
}

New-KeyParameterIfAbsent $ingestParam
New-KeyParameterIfAbsent $readParam

sam build -t $template
sam deploy `
    --stack-name $StackName `
    --capabilities CAPABILITY_IAM `
    --resolve-s3 `
    --no-fail-on-empty-changeset `
    --parameter-overrides "Stage=$Stage" "IngestKeyParameterName=$ingestParam" "ReadKeyParameterName=$readParam"

$apiUrl = aws cloudformation describe-stacks --stack-name $StackName `
    --query "Stacks[0].Outputs[?OutputKey=='ApiBaseUrl'].OutputValue" --output text
Write-Host "ApiBaseUrl: $apiUrl"
Write-Host "Read the ingest key into your local .env with:"
Write-Host "  aws ssm get-parameter --name $ingestParam --with-decryption --query Parameter.Value --output text"
