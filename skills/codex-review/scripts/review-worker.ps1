# Use the exact PATH-selected installed CLI; native argv arrays handled by Python.
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
    $help = Invoke-CodexProbe -Launcher $cli -ProbeArgs @('exec', '--help')
    foreach ($flag in @('--json', '--skip-git-repo-check')) {
        if ($help -notmatch [regex]::Escape($flag)) { throw ('Installed CLI lacks required review flag: ' + $flag) }
    }
    $python = Get-Command python.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1
    $metadata = [IO.Path]::GetTempFileName()
    [IO.File]::WriteAllText($metadata, ($cli | ConvertTo-Json -Depth 4), (New-Object Text.UTF8Encoding($false)))
    $arguments = @((Join-Path $PSScriptRoot 'review_state.py'), 'run', '--spec-file', $SpecFile, '--launcher-file', $metadata)
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
