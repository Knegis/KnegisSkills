<#
.SYNOPSIS
    Kill every live worker in a run, process tree and all.

.DESCRIPTION
    Interrupting Claude does NOT stop detached codex processes - they keep
    editing worktrees while the run looks cancelled. The tree is
    powershell -> node.exe -> codex.exe, so /T is mandatory.

    This never touches git state. Whatever a worker had written stays on disk
    for review; nothing is reverted here.

.NOTES
    PowerShell 5.1. ASCII only.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string] $RunDir
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $RunDir)) {
    Write-Output ("run dir not found: " + $RunDir)
    exit 1
}

$killed = 0
$alreadyGone = 0

foreach ($f in @(Get-ChildItem -LiteralPath $RunDir -Filter 'pid-*.txt' -ErrorAction SilentlyContinue)) {
    $id = $f.BaseName -replace '^pid-', ''
    $procId = 0
    $ok = [int]::TryParse((Get-Content -LiteralPath $f.FullName -Raw).Trim(), [ref]$procId)
    if (-not $ok) { continue }

    $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($null -eq $p) {
        $alreadyGone++
        Write-Output ("worker=" + $id + " pid=" + $procId + " already_gone")
        continue
    }

    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & taskkill.exe /PID $procId /T /F | Out-Null
    $ErrorActionPreference = $prev

    $killed++
    Write-Output ("worker=" + $id + " pid=" + $procId + " killed_tree")

    $statusFile = Join-Path $RunDir ("status-" + $id + ".txt")
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($statusFile, ("worker=" + $id + " state=aborted ts=" + (Get-Date -Format o) + "`n"), $enc)
}

foreach ($f in @(Get-ChildItem -LiteralPath $RunDir -Filter 'lock-*.lock' -ErrorAction SilentlyContinue)) {
    try {
        Remove-Item -LiteralPath $f.FullName -Force
        Write-Output ("released_lock=" + $f.Name)
    } catch {
        Write-Output ("lock still held by a live process: " + $f.Name)
    }
}

# A codex.exe orphaned by an earlier partial kill would keep writing. Report,
# do not kill blind - the user may have an interactive codex session open.
$strays = @(Get-Process -Name 'codex' -ErrorAction SilentlyContinue)
if ($strays.Count -gt 0) {
    Write-Output ("WARN: " + $strays.Count + " codex process(es) still running (pids: " + (($strays | ForEach-Object { $_.Id }) -join ',') + "). These may be your own interactive sessions - check before killing.")
}

Write-Output ("abort=ok killed=" + $killed + " already_gone=" + $alreadyGone)
