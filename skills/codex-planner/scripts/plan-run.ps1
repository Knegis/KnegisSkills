# Planning state CLI. Windows PowerShell 5.1; Python 3.10+ on PATH.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('init', 'status', 'record', 'refresh', 'finalize')][string] $Action,
    [string] $RepoRoot,
    [string] $RunDir,
    [string] $Artifact,
    [string] $InputFile,
    [string] $EvidenceFile,
    [string] $OutputFile,
    [switch] $ContinueReview
)
$ErrorActionPreference = 'Stop'
$python = Get-Command 'python.exe' -CommandType Application -ErrorAction Stop | Select-Object -First 1
$arguments = @((Join-Path $PSScriptRoot 'plan_state.py'), $Action)
foreach ($pair in @(@('--repo-root', $RepoRoot), @('--run-dir', $RunDir), @('--artifact', $Artifact),
                    @('--input-file', $InputFile), @('--evidence-file', $EvidenceFile), @('--output-file', $OutputFile))) {
    if (-not [string]::IsNullOrWhiteSpace($pair[1])) { $arguments += $pair }
}
if ($ContinueReview) { $arguments += '--continue-review' }
& $python.Source @arguments
exit $LASTEXITCODE
