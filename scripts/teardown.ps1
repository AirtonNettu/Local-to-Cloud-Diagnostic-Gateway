# Tear down the diagnostic-gateway stack and its SSM key parameters.
# REQUIRES the AWS and SAM CLIs. This repository never runs this against AWS.
param(
    [string]$StackName = "diagnostic-gateway-dev",
    [string]$Stage = "dev",
    [switch]$Force
)
$ErrorActionPreference = "Stop"

$ingestParam = "/diagnostic-gateway/$Stage/ingest-api-key"
$readParam = "/diagnostic-gateway/$Stage/read-api-key"

foreach ($tool in @("aws", "sam")) {
    if ($null -eq (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "$tool CLI is required but not found on PATH."
    }
}

if (-not $Force) {
    $typed = Read-Host "Type the stack name '$StackName' to confirm deletion"
    if ($typed -ne $StackName) { Write-Host "Aborted."; return }
}

sam delete --stack-name $StackName --no-prompts
aws ssm delete-parameters --names $ingestParam $readParam | Out-Null

Write-Host "Stack and key parameters deleted."
Write-Host "The SAM managed bucket/stack (aws-sam-cli-managed-default) from --resolve-s3 remains."
Write-Host "To remove it, empty then delete the bucket, then delete the stack:"
Write-Host "  aws s3 rm s3://<managed-bucket> --recursive"
Write-Host "  aws cloudformation delete-stack --stack-name aws-sam-cli-managed-default"
