# Discover the installed CLI, then let Python pass native argument arrays.
# No cmd /c, prompt on the command line, or CLI downloads. PowerShell 5.1.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string] $SpecFile,
    [switch] $DryRun,
    [switch] $Retry
)
$ErrorActionPreference = 'Stop'
$metadata = $null
try {
    . (Join-Path $PSScriptRoot 'codex-cli.ps1')
    $cli = Get-CodexCli
    $python = Get-Command 'python.exe' -CommandType Application -ErrorAction Stop | Select-Object -First 1
    $metadata = [System.IO.Path]::GetTempFileName()
    [System.IO.File]::WriteAllText($metadata, ($cli | ConvertTo-Json -Depth 4), (New-Object System.Text.UTF8Encoding($false)))
    $arguments = @((Join-Path $PSScriptRoot 'plan_state.py'), 'run', '--spec-file', $SpecFile, '--launcher-file', $metadata)
    if ($DryRun) { $arguments += '--dry-run' }
    if ($Retry) { $arguments += '--retry' }
    & $python.Source @arguments
    $workerExit = $LASTEXITCODE
} catch {
    Write-Error $_.Exception.Message -ErrorAction Continue
    $workerExit = 13
} finally {
    if ($null -ne $metadata -and (Test-Path -LiteralPath $metadata)) { Remove-Item -LiteralPath $metadata -Force }
}
exit $workerExit
