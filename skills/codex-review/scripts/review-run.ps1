# Context capture/status/assessment. PowerShell 5.1; no model calls.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('init', 'status', 'assess')][string] $Action,
    [string] $RepoRoot,
    [string] $RequestFile,
    [string] $RunDir,
    [string] $InputFile
)
$ErrorActionPreference = 'Stop'
$python = Get-Command python.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1
$arguments = @((Join-Path $PSScriptRoot 'review_state.py'), $Action)
foreach ($pair in @(@('--repo-root', $RepoRoot), @('--request-file', $RequestFile), @('--run-dir', $RunDir), @('--input-file', $InputFile))) {
    if (-not [string]::IsNullOrWhiteSpace($pair[1])) { $arguments += $pair }
}
& $python.Source @arguments
exit $LASTEXITCODE
