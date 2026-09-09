<#
.SYNOPSIS
    One-screen digest of every worker in a run. Read this instead of polling.

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

Write-Output ("run_dir=" + $RunDir)

$statusFiles = @(Get-ChildItem -LiteralPath $RunDir -Filter 'status-*.txt' -ErrorAction SilentlyContinue)
if ($statusFiles.Count -eq 0) {
    Write-Output "no workers have started"
} else {
    foreach ($f in ($statusFiles | Sort-Object Name)) {
        $line = (Get-Content -LiteralPath $f.FullName -Raw).Trim()
        Write-Output $line
    }
}

# Liveness: a status line saying 'running' means nothing if the process is gone.
$pidFiles = @(Get-ChildItem -LiteralPath $RunDir -Filter 'pid-*.txt' -ErrorAction SilentlyContinue)
foreach ($f in ($pidFiles | Sort-Object Name)) {
    $id = $f.BaseName -replace '^pid-', ''
    $procId = 0
    $ok = [int]::TryParse((Get-Content -LiteralPath $f.FullName -Raw).Trim(), [ref]$procId)
    if (-not $ok) { continue }
    $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($null -eq $p) {
        Write-Output ("live worker=" + $id + " pid=" + $procId + " state=gone")
    } else {
        $mins = [int]((Get-Date) - $p.StartTime).TotalMinutes
        Write-Output ("live worker=" + $id + " pid=" + $procId + " state=alive name=" + $p.ProcessName + " running_min=" + $mins)
    }
}

$locks = @(Get-ChildItem -LiteralPath $RunDir -Filter 'lock-*.lock' -ErrorAction SilentlyContinue)
Write-Output ("held_locks=" + $locks.Count)

foreach ($f in @(Get-ChildItem -LiteralPath $RunDir -Filter 'diffstat-*.txt' -ErrorAction SilentlyContinue)) {
    $tail = @(Get-Content -LiteralPath $f.FullName | Where-Object { $_.Trim().Length -gt 0 })
    if ($tail.Count -gt 0) {
        Write-Output ("diffstat " + ($f.BaseName -replace '^diffstat-', '') + ": " + $tail[-1].Trim())
    }
}
