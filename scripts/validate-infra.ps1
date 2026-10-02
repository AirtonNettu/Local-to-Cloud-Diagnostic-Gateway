# Validate the SAM template offline. Never touches an AWS account.
#
# Runs cfn-lint always. Runs `sam validate --lint` only if the SAM CLI is on
# PATH; it is NOT installed on the reference machine, so that step is skipped
# with an explicit note rather than failing.
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$template = Join-Path $repoRoot "infrastructure/template.yaml"
$python = Join-Path $repoRoot ".venv/Scripts/python.exe"

Write-Host "Running cfn-lint on $template"
# cfn-lint 1.x ships a console script but no `python -m cfnlint`; prefer the
# venv console script and fall back to a bare cfn-lint on PATH.
$cfnLint = Join-Path $repoRoot ".venv/Scripts/cfn-lint.exe"
if (Test-Path $cfnLint) {
    & $cfnLint $template
} else {
    & cfn-lint $template
}
if ($LASTEXITCODE -ne 0) {
    throw "cfn-lint reported findings."
}

$sam = Get-Command sam -ErrorAction SilentlyContinue
if ($null -ne $sam) {
    Write-Host "Running sam validate --lint"
    & sam validate --lint -t $template
} else {
    Write-Host "SKIP: sam validate - the SAM CLI is not installed on this machine."
}

Write-Host "Offline infrastructure validation complete."
