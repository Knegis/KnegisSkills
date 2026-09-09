<#
.SYNOPSIS
    Run ONE Codex worker for ONE round against ONE pool worktree.

.DESCRIPTION
    Everything the worker needs is in the spec JSON. Nothing is passed on the
    command line, so the command shape stays constant (one tight permission
    prefix) and multi-KB prompts never touch PowerShell quoting.

    This script never commits, never merges, and never writes to the primary
    checkout. It refuses to run unless the target is a LINKED worktree whose
    HEAD is exactly the run's base commit.

.NOTES
    PowerShell 5.1. No &&, no ||, no ternary, no null-conditional operators.
    ASCII only - a UTF-8 BOM or a non-ASCII byte in a .ps1 misparses under 5.1.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string] $SpecFile,
    [switch] $DryRun
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------- exit codes
#  0  ok                       13 codex.js not found
# 10  bad or missing spec      14 slot already locked
# 11  not a linked worktree    15 run-header assertion failed
# 12  branch or HEAD mismatch  20 codex exited nonzero
# 21  wall-clock timeout       22 result file missing or empty
# 23  result file unusable     24 worker moved HEAD (it committed)
# 26  rate or quota exhaustion detected

$script:Status   = $null
$script:LockFile = $null
$script:Lock     = $null
$script:WorkerId = 'unknown'

function Write-Utf8NoBom {
    param([string] $Path, [string] $Text)
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $enc)
}

function Set-Status {
    param([string] $Line)
    if ($null -ne $script:Status) {
        Write-Utf8NoBom -Path $script:Status -Text ($Line + "`n")
    }
    Write-Output $Line
}

function Release-Lock {
    if ($null -ne $script:Lock) {
        $script:Lock.Close()
        $script:Lock.Dispose()
        $script:Lock = $null
    }
    if ($null -ne $script:LockFile) {
        if (Test-Path -LiteralPath $script:LockFile) {
            Remove-Item -LiteralPath $script:LockFile -Force
        }
    }
}

function Stop-Worker {
    param([int] $Code, [string] $Reason)
    Set-Status ("worker={0} state=error exit={1} reason={2}" -f $script:WorkerId, $Code, $Reason)
    Release-Lock
    exit $Code
}

# Native git, captured without letting NativeCommandError become terminating
# and without Out-String's console-width line wrapping.
function Invoke-Git {
    param([string[]] $GitArgs)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $raw = & git @GitArgs 2>&1
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prev
    $lines = @()
    foreach ($item in $raw) { $lines += $item.ToString() }
    return [pscustomobject]@{ Code = $code; Text = ($lines -join "`n").Trim() }
}

# Big outputs (diffs) go straight to a file as raw bytes - no PowerShell
# encoding layer, no line wrapping.
function Invoke-GitToFile {
    param([string[]] $GitArgs, [string] $OutFile, [string] $ErrFile)
    $p = Start-Process -FilePath 'git.exe' -ArgumentList $GitArgs -NoNewWindow -PassThru `
                       -RedirectStandardOutput $OutFile -RedirectStandardError $ErrFile
    $null = $p.Handle
    $p.WaitForExit()
    return $p.ExitCode
}

function Get-Required {
    param([object] $Obj, [string] $Name)
    if (-not ($Obj.PSObject.Properties.Name -contains $Name)) {
        Stop-Worker -Code 10 -Reason ("spec missing key: " + $Name)
    }
    return $Obj.$Name
}

function Normalize-Path {
    param([string] $P)
    return ($P -replace '\\', '/').TrimEnd('/').ToLowerInvariant()
}

# ------------------------------------------------------------------- 1. spec
if (-not (Test-Path -LiteralPath $SpecFile)) {
    Write-Output ("spec not found: " + $SpecFile)
    exit 10
}
try {
    $spec = Get-Content -LiteralPath $SpecFile -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
    Write-Output ("spec is not valid JSON: " + $_.Exception.Message)
    exit 10
}

$script:WorkerId = Get-Required $spec 'worker_id'
$runId           = Get-Required $spec 'run_id'
$round           = Get-Required $spec 'round'
$repoRoot        = Get-Required $spec 'repo_root'
$worktree        = Get-Required $spec 'worktree'
$branch          = Get-Required $spec 'branch'
$baseSha         = Get-Required $spec 'base_sha'
$runDir          = Get-Required $spec 'run_dir'
$promptFile      = Get-Required $spec 'prompt_file'
$schemaFile      = Get-Required $spec 'schema_file'
$model           = Get-Required $spec 'model'
$effort          = Get-Required $spec 'reasoning_effort'
$sandbox         = Get-Required $spec 'sandbox'
$timeoutSeconds  = Get-Required $spec 'timeout_seconds'

$addDirs    = @()
$ownedPaths = @()
if ($spec.PSObject.Properties.Name -contains 'add_dirs')    { $addDirs    = @($spec.add_dirs) }
if ($spec.PSObject.Properties.Name -contains 'owned_paths') { $ownedPaths = @($spec.owned_paths) }

if (-not (Test-Path -LiteralPath $runDir)) {
    New-Item -ItemType Directory -Path $runDir -Force | Out-Null
}

$id              = $script:WorkerId
$script:Status   = Join-Path $runDir ("status-" + $id + ".txt")
$script:LockFile = Join-Path $runDir ("lock-" + $id + ".lock")
$pidFile         = Join-Path $runDir ("pid-" + $id + ".txt")
$stdoutLog       = Join-Path $runDir ("stdout-" + $id + ".log")
$stderrLog       = Join-Path $runDir ("stderr-" + $id + ".log")
$resultFile      = Join-Path $runDir ("result-" + $id + ".json")
$patchFile       = Join-Path $runDir ("patch-" + $id + ".diff")
$diffstatFile    = Join-Path $runDir ("diffstat-" + $id + ".txt")
$changesFile     = Join-Path $runDir ("changes-" + $id + ".txt")
$violationsFile  = Join-Path $runDir ("violations-" + $id + ".txt")
$gitErrFile      = Join-Path $runDir ("giterr-" + $id + ".log")

Set-Status ("worker={0} round={1} state=starting pid={2} ts={3}" -f $id, $round, $PID, (Get-Date -Format o))

foreach ($f in @($promptFile, $schemaFile)) {
    if (-not (Test-Path -LiteralPath $f)) {
        Stop-Worker -Code 10 -Reason ("missing file: " + $f)
    }
    if ((Get-Item -LiteralPath $f).Length -eq 0) {
        Stop-Worker -Code 10 -Reason ("empty file: " + $f)
    }
}

# A UTF-8 BOM at the head of stdin is a real corruption vector for the prompt.
$promptBytes = [System.IO.File]::ReadAllBytes($promptFile)
if ($promptBytes.Length -ge 3) {
    if ($promptBytes[0] -eq 0xEF -and $promptBytes[1] -eq 0xBB -and $promptBytes[2] -eq 0xBF) {
        Stop-Worker -Code 10 -Reason 'prompt_file has a UTF-8 BOM; rewrite it without one'
    }
}

# --------------------------------------------------- 2-5. worktree identity
# --path-format=absolute on BOTH is mandatory: without it --git-common-dir
# returns the relative ".git" in a primary checkout, the strings never match,
# and the primary-checkout guard below silently passes.
$gitDir    = Invoke-Git @('-C', $worktree, 'rev-parse', '--path-format=absolute', '--git-dir')
$commonDir = Invoke-Git @('-C', $worktree, 'rev-parse', '--path-format=absolute', '--git-common-dir')
if ($gitDir.Code -ne 0) {
    Stop-Worker -Code 11 -Reason ("not a git worktree: " + $gitDir.Text)
}
if ($commonDir.Code -ne 0) {
    Stop-Worker -Code 11 -Reason ("cannot resolve common dir: " + $commonDir.Text)
}

# THE load-bearing guard: a linked worktree has its own gitdir. If these match,
# the target is the primary checkout and codex must never be pointed at it.
if ((Normalize-Path $gitDir.Text) -eq (Normalize-Path $commonDir.Text)) {
    Stop-Worker -Code 11 -Reason 'target is the PRIMARY checkout, not a linked worktree'
}

$topLevel = Invoke-Git @('-C', $worktree, 'rev-parse', '--show-toplevel')
if ($topLevel.Code -ne 0) {
    Stop-Worker -Code 11 -Reason 'cannot resolve worktree toplevel'
}
if ((Normalize-Path $topLevel.Text) -ne (Normalize-Path $worktree)) {
    Stop-Worker -Code 11 -Reason ("worktree path mismatch: git says " + $topLevel.Text)
}

$curBranch = Invoke-Git @('-C', $worktree, 'symbolic-ref', '--quiet', '--short', 'HEAD')
if ($curBranch.Code -ne 0) {
    Stop-Worker -Code 12 -Reason 'worktree is in detached HEAD'
}
if ($curBranch.Text -ne $branch) {
    Stop-Worker -Code 12 -Reason ("branch mismatch: on " + $curBranch.Text + ", expected " + $branch)
}

$curHead = Invoke-Git @('-C', $worktree, 'rev-parse', 'HEAD')
if ($curHead.Code -ne 0) {
    Stop-Worker -Code 12 -Reason 'cannot resolve worktree HEAD'
}
if ($curHead.Text -ne $baseSha) {
    Stop-Worker -Code 12 -Reason ("HEAD is " + $curHead.Text + ", expected base " + $baseSha)
}

# --------------------------------------------------------- 6. exclusive slot
try {
    $script:Lock = [System.IO.File]::Open($script:LockFile, 'CreateNew', 'Write', 'None')
} catch {
    Write-Output ("slot " + $id + " is already locked by a live run: " + $script:LockFile)
    $script:LockFile = $null
    exit 14
}

# ------------------------------------------------------- 7. resolve node/cli
# Start-Process with redirects uses CreateProcess, which cannot launch a .cmd
# batch shim, and cmd.exe /c would re-parse and mangle -c key="value". Run
# codex.js under node directly. Not codex.exe: codex.js is what wires the
# bundled rg.exe and the Windows sandbox helper into the child environment.
$codexJs = $null
$cmdShim = Get-Command 'codex.cmd' -CommandType Application -ErrorAction SilentlyContinue
if ($null -ne $cmdShim) {
    $candidate = Join-Path (Split-Path $cmdShim.Source -Parent) 'node_modules\@openai\codex\bin\codex.js'
    if (Test-Path -LiteralPath $candidate) { $codexJs = $candidate }
}
if ($null -eq $codexJs) {
    $candidate = Join-Path $env:APPDATA 'npm\node_modules\@openai\codex\bin\codex.js'
    if (Test-Path -LiteralPath $candidate) { $codexJs = $candidate }
}
if ($null -eq $codexJs) {
    Stop-Worker -Code 13 -Reason 'cannot locate codex.js'
}

$nodeCmd = Get-Command 'node.exe' -CommandType Application -ErrorAction SilentlyContinue
if ($null -eq $nodeCmd) {
    Stop-Worker -Code 13 -Reason 'node.exe not on PATH'
}

$argList = @()
$argList += ('"' + $codexJs + '"')
$argList += 'exec'
$argList += @('-C', ('"' + $worktree + '"'))
$argList += @('--sandbox', $sandbox)
$argList += @('-c', 'approval_policy="never"')
$argList += @('-c', ('model_reasoning_effort="' + $effort + '"'))
$argList += '--ephemeral'
$argList += @('--color', 'never')
$argList += @('-m', $model)
$argList += @('--output-schema', ('"' + $schemaFile + '"'))
$argList += @('-o', ('"' + $resultFile + '"'))
foreach ($d in $addDirs) {
    $argList += @('--add-dir', ('"' + $d + '"'))
}
$argList += '-'

# Enumerate the member objects, not .Name: with "env": {} the Name lookup on an
# empty member collection throws under StrictMode.
if ($spec.PSObject.Properties.Name -contains 'env') {
    foreach ($prop in @($spec.env.PSObject.Properties)) {
        Set-Item -Path ("Env:" + $prop.Name) -Value ([string]$prop.Value)
    }
}

if ($DryRun) {
    Set-Status ("worker={0} state=dryrun node={1} args={2}" -f $id, $nodeCmd.Source, ($argList -join ' '))
    Release-Lock
    exit 0
}

# ---------------------------------------------------------------- 8. run it
if (Test-Path -LiteralPath $resultFile) {
    Remove-Item -LiteralPath $resultFile -Force
}

Set-Status ("worker={0} round={1} state=running model={2} effort={3} ts={4}" -f $id, $round, $model, $effort, (Get-Date -Format o))
$started = Get-Date

$proc = Start-Process -FilePath $nodeCmd.Source -ArgumentList $argList `
                      -WorkingDirectory $worktree -NoNewWindow -PassThru `
                      -RedirectStandardInput $promptFile `
                      -RedirectStandardOutput $stdoutLog `
                      -RedirectStandardError $stderrLog
$null = $proc.Handle   # cache the handle, or ExitCode can come back null later
Write-Utf8NoBom -Path $pidFile -Text ([string]$proc.Id)

$timedOut = $false
$codexExit = 0
$finished = $proc.WaitForExit([int]$timeoutSeconds * 1000)
if (-not $finished) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & taskkill.exe /PID $proc.Id /T /F | Out-Null   # /T is mandatory: node -> codex.exe
    $ErrorActionPreference = $prev
    $timedOut = $true
    $codexExit = 9009
} else {
    $codexExit = $proc.ExitCode
}
$duration = [int]((Get-Date) - $started).TotalSeconds

# ------------------------------------------------------------ 9. post-flight
$headAfter = Invoke-Git @('-C', $worktree, 'rev-parse', 'HEAD')
$movedHead = $false
if ($headAfter.Code -eq 0) {
    if ($headAfter.Text -ne $baseSha) { $movedHead = $true }
}

# --intent-to-add makes new files visible to git diff without creating a commit.
$null = Invoke-Git @('-C', $worktree, 'add', '--intent-to-add', '-A')
$null = Invoke-GitToFile -GitArgs @('-C', $worktree, 'diff', '--no-color') -OutFile $patchFile -ErrFile $gitErrFile
$null = Invoke-GitToFile -GitArgs @('-C', $worktree, 'diff', '--stat', '--no-color') -OutFile $diffstatFile -ErrFile $gitErrFile
$null = Invoke-GitToFile -GitArgs @('-C', $worktree, 'status', '--porcelain') -OutFile $changesFile -ErrFile $gitErrFile

$insertions   = 0
$deletions    = 0
$filesTouched = 0
if (Test-Path -LiteralPath $changesFile) {
    $filesTouched = @(Get-Content -LiteralPath $changesFile | Where-Object { $_.Trim().Length -gt 0 }).Count
}
if (Test-Path -LiteralPath $patchFile) {
    foreach ($line in Get-Content -LiteralPath $patchFile) {
        if ($line.StartsWith('+') -and (-not $line.StartsWith('+++'))) { $insertions++ }
        if ($line.StartsWith('-') -and (-not $line.StartsWith('---'))) { $deletions++ }
    }
}

# Assert the run header rather than trusting that the -c flags took effect.
# The header lives on STDERR: with --output-schema, stdout carries only the
# final JSON object and nothing else.
$headerOk = $true
$headerNotes = @()
if (Test-Path -LiteralPath $stderrLog) {
    $headerText = (@(Get-Content -LiteralPath $stderrLog -TotalCount 20) -join "`n")
    if ($headerText -notmatch 'approval:\s*never') {
        $headerOk = $false
        $headerNotes += 'approval-not-never'
    }
    if ($headerText -notmatch ('model:\s*' + [regex]::Escape($model))) {
        $headerOk = $false
        $headerNotes += 'model-mismatch'
    }
    if ($headerText -notmatch ('sandbox:\s*' + [regex]::Escape($sandbox))) {
        $headerOk = $false
        $headerNotes += 'sandbox-mismatch'
    }
    # Proves -C took effect, i.e. codex really ran against the slot and not
    # against whatever directory the launching shell happened to be in.
    if ($headerText -notmatch ('workdir:\s*' + [regex]::Escape($worktree))) {
        $headerOk = $false
        $headerNotes += 'workdir-mismatch'
    }
} else {
    $headerOk = $false
    $headerNotes += 'no-stderr'
}
$headerNote = 'ok'
if ($headerNotes.Count -gt 0) { $headerNote = ($headerNotes -join '+') }

# Rate and quota exhaustion is not a retryable condition; surface it distinctly.
# The pattern is matched against the whole transcript, which includes every
# repository file the model read, so it is only believed when codex itself
# failed or produced no usable result. Measured 2026-09-02: a clean run that
# read docs mentioning provider "rate limits" was reported as 26 with a
# complete result behind it.
$quotaHit = $false
foreach ($logFile in @($stdoutLog, $stderrLog)) {
    if (Test-Path -LiteralPath $logFile) {
        $hit = Select-String -LiteralPath $logFile -Pattern 'rate limit|429|usage limit|quota exceeded' -Quiet
        if ($hit) { $quotaHit = $true }
    }
}

# Ownership check: report only in v1, so a benign stray edit does not fail an
# otherwise good round. Claude decides what to do with the list.
$violationCount = 0
if ($ownedPaths.Count -gt 0) {
    $violations = @()
    if (Test-Path -LiteralPath $changesFile) {
        foreach ($line in Get-Content -LiteralPath $changesFile) {
            if ($line.Trim().Length -lt 4) { continue }
            $p = $line.Substring(3).Trim().Trim('"')
            $owned = $false
            foreach ($glob in $ownedPaths) {
                if ($p -like $glob) { $owned = $true }
            }
            if (-not $owned) { $violations += $p }
        }
    }
    $violationCount = $violations.Count
    Write-Utf8NoBom -Path $violationsFile -Text (($violations -join "`n") + "`n")
}

# Result JSON: shallow structural check only. PS 5.1 has no Test-Json, and real
# schema validation here would be theatre.
$resultState = 'ok'
$resultCode  = 0
if (-not (Test-Path -LiteralPath $resultFile)) {
    $resultState = 'missing'
    $resultCode  = 22
} elseif ((Get-Item -LiteralPath $resultFile).Length -eq 0) {
    $resultState = 'empty'
    $resultCode  = 22
} else {
    try {
        $res = Get-Content -LiteralPath $resultFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $valid = $true
        if (-not ($res.PSObject.Properties.Name -contains 'status')) { $valid = $false }
        if ($valid) {
            if (@('complete', 'partial', 'blocked', 'failed') -notcontains $res.status) { $valid = $false }
        }
        foreach ($arrKey in @('files_changed', 'tests_run', 'blockers')) {
            if (-not ($res.PSObject.Properties.Name -contains $arrKey)) { $valid = $false }
        }
        if (-not $valid) {
            $resultState = 'unusable'
            $resultCode  = 23
        } else {
            $resultState = $res.status
        }
    } catch {
        $resultState = 'unparseable'
        $resultCode  = 23
    }
}

# --------------------------------------------------------- 10. verdict, once
$exitCode = 0
if ($quotaHit -and (($codexExit -ne 0) -or ($resultCode -ne 0))) {
    $exitCode = 26
} elseif ($movedHead) {
    $exitCode = 24
} elseif ($timedOut) {
    $exitCode = 21
} elseif (-not $headerOk) {
    $exitCode = 15
} elseif ($codexExit -ne 0) {
    $exitCode = 20
} elseif ($resultCode -ne 0) {
    $exitCode = $resultCode
}

$line = ("worker={0} round={1} state=done exit={2} codex_exit={3} dur={4}s files={5} ins={6} del={7} result={8} header={9} violations={10}" -f `
    $id, $round, $exitCode, $codexExit, $duration, $filesTouched, $insertions, $deletions, $resultState, $headerNote, $violationCount)
Set-Status $line

Release-Lock
exit $exitCode
