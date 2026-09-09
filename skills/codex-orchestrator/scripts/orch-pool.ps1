<#
.SYNOPSIS
    Prepare and integrate the warm worktree pool. Refuses rather than guesses.

.DESCRIPTION
    -Action preflight   Read-only checks on the primary checkout, plus discovery:
                        hardware, ecosystems (by manifest), derived pool and run
                        roots, permission coverage. Nonzero exit means do not
                        start a run.
    -Action allocate    Print one JSON slot descriptor per worker
                        ({slot, worktree, branch}). No git side effects.
    -Action reset       Put one pool slot on a fresh branch at the base commit,
                        preserving warm build output. Aborts on anything it
                        cannot do safely.
    -Action commit      Commit an approved slot's work. The commit is the
                        approval gate, so only the orchestrator calls this.

    Slots are named <slot_prefix><N> with 1 <= N <= max_workers (default
    worker-1 .. worker-4). Defaults are below; an optional
    ~/.claude/codex-orchestrator.json overrides them.

    NEVER runs: git worktree prune, git worktree remove, git clean -x/-X/-fdx,
    git branch -D, git switch -C, git push. A locked worktree or any path
    outside the slot pattern is an immediate abort.

.NOTES
    PowerShell 5.1. ASCII only. No &&, no ||, no ternary.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('preflight', 'allocate', 'reset', 'commit')]
    [string] $Action,

    [Parameter(Mandatory = $true)][string] $RepoRoot,
    [string]   $PoolRoot,
    [string]   $Slot,
    [string]   $Branch,
    [string]   $BaseSha,
    [string]   $MessageFile,
    [string]   $RunId,
    [string[]] $Slugs,
    [int]      $MinFreeGb = 0
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$BS = [string][char]92   # a backslash built from its code, so no literal has to survive quoting

# Exit codes: 0 ok | 30 preflight refusal | 31 reset refusal | 32 commit refusal
#             33 bad arguments or bad config | 34 allocate refusal

function Fail {
    param([int] $Code, [string] $Reason)
    Write-Output ("ABORT: " + $Reason)
    exit $Code
}

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

function Normalize-Path {
    param([string] $P)
    return ($P.Replace($BS, "/")).TrimEnd("/").ToLowerInvariant()
}

# StrictMode 2.0 throws on a missing property, so every read of a
# ConvertFrom-Json object goes through this first.
function Test-Prop {
    param([object] $Obj, [string] $Name)
    if ($null -eq $Obj) { return $false }
    return ($Obj.PSObject.Properties.Name -contains $Name)
}

function Assert-LinkedWorktree {
    param([string] $Path, [int] $Code)
    # --path-format=absolute on BOTH: --git-common-dir is relative (".git") in a
    # primary checkout, which would make the comparison below never match.
    $gd = Invoke-Git @('-C', $Path, 'rev-parse', '--path-format=absolute', '--git-dir')
    $cd = Invoke-Git @('-C', $Path, 'rev-parse', '--path-format=absolute', '--git-common-dir')
    if ($gd.Code -ne 0) { Fail $Code ("not a git worktree: " + $Path) }
    if ($cd.Code -ne 0) { Fail $Code ("cannot resolve common gitdir for " + $Path) }
    if ((Normalize-Path $gd.Text) -eq (Normalize-Path $cd.Text)) {
        Fail $Code ("refusing to touch the PRIMARY checkout at " + $Path)
    }
}

# The inverse: RepoRoot must be the primary checkout (its gitdir IS the common
# gitdir). Returns the absolute gitdir path.
function Assert-PrimaryCheckout {
    param([int] $Code)
    $gd = Invoke-Git @('-C', $RepoRoot, 'rev-parse', '--path-format=absolute', '--git-dir')
    $cd = Invoke-Git @('-C', $RepoRoot, 'rev-parse', '--path-format=absolute', '--git-common-dir')
    if (($gd.Code -ne 0) -or ($cd.Code -ne 0)) { Fail $Code 'cannot resolve the gitdir of RepoRoot' }
    if ((Normalize-Path $gd.Text) -ne (Normalize-Path $cd.Text)) {
        Fail $Code 'RepoRoot is a linked worktree; invoke from the primary checkout'
    }
    return $gd.Text
}

# Parse `git worktree list --porcelain` into path -> flags.
function Get-WorktreeTable {
    $out = Invoke-Git @('-C', $RepoRoot, 'worktree', 'list', '--porcelain')
    if ($out.Code -ne 0) { Fail 30 'git worktree list failed' }
    $table = @{}
    $cur = $null
    foreach ($line in ($out.Text -split "`n")) {
        $t = $line.Trim()
        if ($t.StartsWith('worktree ')) {
            $cur = Normalize-Path $t.Substring(9)
            $table[$cur] = [pscustomobject]@{
                Path = $t.Substring(9); Locked = $false; Prunable = $false; Detached = $false; Branch = ''
            }
        } elseif ($null -ne $cur) {
            if ($t.StartsWith('locked'))   { $table[$cur].Locked = $true }
            if ($t.StartsWith('prunable')) { $table[$cur].Prunable = $true }
            if ($t -eq 'detached')         { $table[$cur].Detached = $true }
            if ($t.StartsWith('branch '))  { $table[$cur].Branch = $t.Substring(7) }
        }
    }
    return $table
}

# ------------------------------------------------------------------- config
# Defaults here; ~/.claude/codex-orchestrator.json may override any key. An
# invalid file is exit 33, never a silent fall back: a typo in max_workers must
# not quietly restore the default ceiling.
$Config = [ordered]@{
    slot_prefix      = 'worker-'
    max_workers      = 4
    min_free_gb      = 10
    run_root         = (Join-Path $HOME '.claude\orch-runs')
    pool_root_suffix = '-worktrees'
}
$ConfigFile = Join-Path $HOME '.claude\codex-orchestrator.json'
if (Test-Path -LiteralPath $ConfigFile) {
    $user = $null
    try {
        $user = Get-Content -LiteralPath $ConfigFile -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        Fail 33 ("config is not valid JSON: " + $ConfigFile + " (" + $_.Exception.Message + ")")
    }
    if ($null -eq $user) { Fail 33 ("config is empty: " + $ConfigFile) }
    foreach ($key in @($user.PSObject.Properties.Name)) {
        if (-not $Config.Contains($key)) {
            Fail 33 ("unknown config key '" + $key + "' in " + $ConfigFile)
        }
        $val = $user.$key
        if (($key -eq 'max_workers') -or ($key -eq 'min_free_gb')) {
            $isNum = ($val -is [int]) -or ($val -is [long]) -or ($val -is [double]) -or ($val -is [decimal])
            if (-not $isNum) { Fail 33 ("config key '" + $key + "' must be a number in " + $ConfigFile) }
            if ([math]::Floor($val) -ne $val) { Fail 33 ("config key '" + $key + "' must be an integer in " + $ConfigFile) }
            if (($key -eq 'max_workers') -and ($val -lt 1)) { Fail 33 ("config key 'max_workers' must be >= 1 in " + $ConfigFile) }
            if ($val -lt 0) { Fail 33 ("config key '" + $key + "' must be >= 0 in " + $ConfigFile) }
            $Config[$key] = [int]$val
        } else {
            if (-not ($val -is [string])) { Fail 33 ("config key '" + $key + "' must be a string in " + $ConfigFile) }
            if ([string]::IsNullOrWhiteSpace($val)) { Fail 33 ("config key '" + $key + "' must not be empty in " + $ConfigFile) }
            $Config[$key] = [string]$val
        }
    }
    if ($Config.run_root.StartsWith('~')) {
        $Config.run_root = Join-Path $HOME ($Config.run_root.Substring(1).TrimStart('/', '\'))
    }
}
$SlotPattern = '^' + [regex]::Escape($Config.slot_prefix) + '([1-9][0-9]*)$'

function Assert-Slot {
    param([string] $Name, [int] $Code)
    $m = [regex]::Match($Name, $SlotPattern)
    if (-not $m.Success) {
        Fail $Code ("slot '" + $Name + "' does not match the slot pattern " + $SlotPattern)
    }
    $n = [int]$m.Groups[1].Value
    if ($n -gt $Config.max_workers) {
        Fail $Code ("slot '" + $Name + "' exceeds max_workers=" + $Config.max_workers)
    }
}

# ---------------------------------------------------------- shared discovery
$top = Invoke-Git @('-C', $RepoRoot, 'rev-parse', '--show-toplevel')
if ($top.Code -ne 0) { Fail 33 'RepoRoot is not a git repository' }
# Repo name from git's own toplevel, not from $RepoRoot: a trailing backslash
# on the argument makes Split-Path -Leaf return an empty string.
$RepoTop  = $top.Text.Replace("/", $BS)
$RepoName = Split-Path -Path $RepoTop -Leaf
$DerivedPoolRoot = Join-Path (Split-Path -Path $RepoTop -Parent) ($RepoName + $Config.pool_root_suffix)
$RunRootForRepo  = Join-Path $Config.run_root $RepoName
if ([string]::IsNullOrWhiteSpace($PoolRoot)) { $PoolRoot = $DerivedPoolRoot }

# Ecosystems: manifest patterns, lockfiles, the store beside the manifest, and a
# rough per-concurrent-build memory weight in GB for recommended_workers.
$EcoTable = @(
    [pscustomobject]@{ Name = 'node';   Files = @('package.json');   Locks = @('package-lock.json', 'pnpm-lock.yaml', 'yarn.lock'); Store = 'node_modules'; Gb = 2 },
    [pscustomobject]@{ Name = 'rust';   Files = @('Cargo.toml');     Locks = @('Cargo.lock');                                        Store = 'target';       Gb = 6 },
    [pscustomobject]@{ Name = 'python'; Files = @('pyproject.toml'); Locks = @('uv.lock', 'poetry.lock', 'requirements.txt');       Store = '.venv';        Gb = 1 },
    [pscustomobject]@{ Name = 'go';     Files = @('go.mod');         Locks = @('go.sum');                                            Store = '';             Gb = 1 },
    [pscustomobject]@{ Name = 'maven';  Files = @('pom.xml');        Locks = @();                                                    Store = '';             Gb = 3 },
    [pscustomobject]@{ Name = 'gradle'; Files = @('build.gradle', 'build.gradle.kts'); Locks = @('gradle.lockfile');                Store = '';             Gb = 3 },
    [pscustomobject]@{ Name = 'dotnet'; Files = @('*.sln', '*.csproj'); Locks = @('packages.lock.json');                            Store = 'obj';          Gb = 2 }
)
# Never descend into these: they are output or stores, never sources of manifests.
$PruneDirs = @('node_modules', 'target', '.git', 'dist', '.venv', 'build', 'bin', 'obj', '.gradle')

# Depth-limited, pruning scan. Not Get-ChildItem -Recurse -Depth: that still
# walks the excluded trees to the depth limit, and -Include is unreliable in 5.1.
function Find-Manifests {
    param([string] $Dir, [int] $Depth, [string] $Rel, [System.Collections.ArrayList] $Acc)
    $items = @(Get-ChildItem -LiteralPath $Dir -Force -ErrorAction SilentlyContinue)
    foreach ($f in $items) {
        if ($f.PSIsContainer) { continue }
        foreach ($eco in $EcoTable) {
            foreach ($pattern in $eco.Files) {
                if ($f.Name -like $pattern) {
                    $relFile = $f.Name
                    if ($Rel.Length -gt 0) { $relFile = $Rel + '/' + $f.Name }
                    $null = $Acc.Add([pscustomobject]@{
                        Eco = $eco.Name; Store = $eco.Store; Locks = $eco.Locks; Gb = $eco.Gb
                        Dir = $Dir; Rel = $Rel; RelFile = $relFile; Depth = $Depth; Root = $false
                    })
                }
            }
        }
    }
    if ($Depth -ge 2) { return }
    foreach ($d in $items) {
        if (-not $d.PSIsContainer) { continue }
        if ($PruneDirs -contains $d.Name) { continue }
        if (([int]$d.Attributes -band [int][System.IO.FileAttributes]::ReparsePoint) -ne 0) { continue }
        $childRel = $d.Name
        if ($Rel.Length -gt 0) { $childRel = $Rel + '/' + $d.Name }
        Find-Manifests -Dir $d.FullName -Depth ($Depth + 1) -Rel $childRel -Acc $Acc
    }
}

# Returns the manifests under $Dir with Root=$true on the shallowest per ecosystem.
function Get-Manifests {
    param([string] $Dir)
    $acc = New-Object System.Collections.ArrayList
    Find-Manifests -Dir $Dir -Depth 0 -Rel '' -Acc $acc
    $minDepth = @{}
    foreach ($m in $acc) {
        if (-not $minDepth.ContainsKey($m.Eco)) { $minDepth[$m.Eco] = $m.Depth }
        elseif ($m.Depth -lt $minDepth[$m.Eco]) { $minDepth[$m.Eco] = $m.Depth }
    }
    foreach ($m in $acc) {
        if ($m.Depth -eq $minDepth[$m.Eco]) { $m.Root = $true }
    }
    return $acc
}

function Get-LockPresent {
    param([object] $Manifest)
    foreach ($lock in $Manifest.Locks) {
        if (Test-Path -LiteralPath (Join-Path $Manifest.Dir $lock)) { return 'yes' }
    }
    return 'no'
}

function Get-DepsPresent {
    param([object] $Manifest)
    if ($Manifest.Store.Length -eq 0) { return 'n/a' }
    if (Test-Path -LiteralPath (Join-Path $Manifest.Dir $Manifest.Store)) { return 'yes' }
    return 'no'
}

# Prefix coverage: an additionalDirectories entry covers itself and everything
# below it. Entries may use ~ or %VAR%.
function Test-Covered {
    param([string] $Path, [string[]] $Entries)
    $p = Normalize-Path $Path
    foreach ($e in $Entries) {
        if ([string]::IsNullOrWhiteSpace($e)) { continue }
        $expanded = [Environment]::ExpandEnvironmentVariables($e)
        if ($expanded.StartsWith('~')) { $expanded = Join-Path $HOME ($expanded.Substring(1).TrimStart('/', '\')) }
        $n = Normalize-Path $expanded
        if ($p -eq $n) { return $true }
        if ($p.StartsWith($n + '/')) { return $true }
    }
    return $false
}

function Write-PathLine {
    param([string] $Key, [string] $Path)
    # JSON-quoted so a path with spaces survives line-oriented parsing.
    Write-Output ($Key + '=' + (ConvertTo-Json $Path -Compress))
}

# ------------------------------------------------------------------ preflight
if ($Action -eq 'preflight') {
    $gitDirPath = Assert-PrimaryCheckout -Code 30

    $branchNow = Invoke-Git @('-C', $RepoRoot, 'symbolic-ref', '--quiet', '--short', 'HEAD')
    if ($branchNow.Code -ne 0) { Fail 30 'primary checkout is in detached HEAD' }

    $base = Invoke-Git @('-C', $RepoRoot, 'rev-parse', 'HEAD')
    if ($base.Code -ne 0) { Fail 30 'cannot resolve HEAD' }

    $dirty = Invoke-Git @('-C', $RepoRoot, 'status', '--porcelain', '--untracked-files=no')
    if ($dirty.Text.Length -gt 0) {
        Write-Output $dirty.Text
        Fail 30 'primary checkout has modified or staged tracked files; commit or stash first'
    }

    $inProgress = @()
    foreach ($marker in @('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'BISECT_LOG', 'rebase-merge', 'rebase-apply')) {
        if (Test-Path -LiteralPath (Join-Path $gitDirPath $marker)) { $inProgress += $marker }
    }
    if ($inProgress.Count -gt 0) {
        Fail 30 ('an operation is in progress (' + ($inProgress -join ', ') + '); finish or abort it first')
    }

    $untracked = Invoke-Git @('-C', $RepoRoot, 'status', '--porcelain')
    $untrackedCount = 0
    foreach ($line in ($untracked.Text -split "`n")) {
        if ($line.StartsWith('??')) { $untrackedCount++ }
    }

    $longPaths = Invoke-Git @('-C', $RepoRoot, 'config', '--get', 'core.longpaths')
    $lpValue = 'unset'
    if ($longPaths.Code -eq 0) { $lpValue = $longPaths.Text }
    $autocrlf = Invoke-Git @('-C', $RepoRoot, 'config', '--get', 'core.autocrlf')
    $acValue = 'unset'
    if ($autocrlf.Code -eq 0) { $acValue = $autocrlf.Text }

    Write-Output ("invoke_branch=" + $branchNow.Text)
    Write-Output ("base_sha=" + $base.Text)
    Write-Output ("untracked_files=" + $untrackedCount)
    Write-Output ("core.longpaths=" + $lpValue)
    Write-Output ("core.autocrlf=" + $acValue)
    Write-PathLine 'repo_root' $RepoTop
    Write-PathLine 'pool_root' $PoolRoot
    Write-PathLine 'run_root' $RunRootForRepo
    $poolExists = 'no'
    if (Test-Path -LiteralPath $PoolRoot) { $poolExists = 'yes' }
    Write-Output ("pool_root_exists=" + $poolExists)

    # Hardware. ProcessorCount is instant; the first CIM call can take a second.
    $cpus = [Environment]::ProcessorCount
    $os = $null
    try { $os = Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop } catch { $os = $null }
    $memTotal = 0.0
    $memFree  = 0.0
    if ($null -ne $os) {
        # CIM reports KB; KB / 1MB is GB.
        $memTotal = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
        $memFree  = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
    }
    Write-Output ("logical_cpus=" + $cpus)
    if ($null -ne $os) {
        Write-Output ("mem_total_gb=" + $memTotal)
        Write-Output ("mem_free_gb=" + $memFree)
    } else {
        Write-Output "WARN: could not query memory via CIM; mem_total_gb and mem_free_gb unknown"
    }
    Write-Output ("max_workers=" + $Config.max_workers)
    $jobs = @()
    for ($n = 1; $n -le $Config.max_workers; $n++) {
        $j = [int][math]::Floor($cpus / $n)
        if ($j -lt 1) { $j = 1 }
        $jobs += ($n.ToString() + ':' + $j.ToString())
    }
    Write-Output ("build_jobs=" + ($jobs -join ' '))

    # Ecosystems, shallow scan of the primary checkout.
    $manifests = @(Get-Manifests -Dir $RepoTop)
    $heaviest = 1
    if ($manifests.Count -eq 0) {
        Write-Output "ecosystem=none (no manifest found within depth 2)"
    }
    foreach ($m in $manifests) {
        $rootFlag = 'no'
        if ($m.Root) { $rootFlag = 'yes' }
        Write-Output ("ecosystem=" + $m.Eco + " manifest=" + $m.RelFile + " root=" + $rootFlag + " lockfile=" + (Get-LockPresent $m) + " deps_present=" + (Get-DepsPresent $m))
        if ($m.Gb -gt $heaviest) { $heaviest = $m.Gb }
    }

    # A ceiling, not a target: SKILL.md's 1/2/more rule still applies under it.
    $rec = $Config.max_workers
    $byCpu = [int][math]::Floor($cpus / 2)
    if ($byCpu -lt 1) { $byCpu = 1 }
    if ($byCpu -lt $rec) { $rec = $byCpu }
    $byMem = -1
    if ($null -ne $os) {
        $byMem = [int][math]::Floor($memFree / $heaviest)
        if ($byMem -lt $rec) { $rec = $byMem }
    }
    if ($rec -lt 1) { $rec = 1 }
    $memNote = 'unknown'
    if ($byMem -ge 0) { $memNote = $byMem.ToString() }
    Write-Output ("recommended_workers=" + $rec + " (heuristic: max_workers=" + $Config.max_workers + " cpus/2=" + $byCpu + " mem_free/" + $heaviest + "GB=" + $memNote + ")")

    # Slots named under an older scheme: informational only.
    if (Test-Path -LiteralPath $PoolRoot) {
        foreach ($d in @(Get-ChildItem -LiteralPath $PoolRoot -Directory -ErrorAction SilentlyContinue)) {
            if ($d.Name -match '^orch-[a-d]$') { Write-Output ("legacy_slot=" + $d.Name) }
        }
    }

    # Persistent permission coverage. WARN only; the run can still proceed with
    # per-call approvals, it will just prompt.
    $settingsFile = Join-Path $HOME '.claude\settings.json'
    $entries = @()
    if (Test-Path -LiteralPath $settingsFile) {
        try {
            $settings = Get-Content -LiteralPath $settingsFile -Raw -Encoding UTF8 | ConvertFrom-Json
            if (Test-Prop $settings 'permissions') {
                if (Test-Prop $settings.permissions 'additionalDirectories') {
                    $entries = @($settings.permissions.additionalDirectories)
                }
            }
        } catch {
            Write-Output ("WARN: could not parse " + $settingsFile + ": " + $_.Exception.Message)
        }
    } else {
        Write-Output ("WARN: settings file not found: " + $settingsFile)
    }
    if (-not (Test-Covered -Path $PoolRoot -Entries $entries)) {
        Write-Output ("WARN: additionalDirectories does not cover pool_root " + $PoolRoot + " - add it in " + $settingsFile + " (see references/setup.md)")
    }
    if (-not (Test-Covered -Path $RunRootForRepo -Entries $entries)) {
        Write-Output ("WARN: additionalDirectories does not cover run_root " + $RunRootForRepo + " - add it in " + $settingsFile + " (see references/setup.md)")
    }

    # Free space on the POOL root's drive, which is where the builds land.
    $spaceRoot = [System.IO.Path]::GetPathRoot($PoolRoot)
    $freeGb = -1
    if ($spaceRoot.StartsWith($BS + $BS)) {
        Write-Output "WARN: pool root is a UNC path; free space not checked"
    } else {
        $drive = Get-PSDrive -Name $spaceRoot.Substring(0, 1) -ErrorAction SilentlyContinue
        if ($null -eq $drive) { Fail 30 ("cannot resolve the drive for pool root " + $PoolRoot) }
        $freeGb = [math]::Round($drive.Free / 1GB, 1)
        Write-Output ("free_gb=" + $freeGb)
    }
    $minFree = $Config.min_free_gb
    if ($MinFreeGb -gt 0) { $minFree = $MinFreeGb }

    if ($lpValue -ne 'true') {
        Write-Output "WARN: core.longpaths is not true. A pool worktree sits one directory deeper than the main checkout, and deep build-output paths will hit MAX_PATH. Fix with: git config --global core.longpaths true"
    }
    if (($freeGb -ge 0) -and ($freeGb -lt $minFree)) {
        Fail 30 ("only " + $freeGb + " GB free on the pool root's drive; need at least " + $minFree + " GB (min_free_gb)")
    }

    Write-Output "preflight=ok"
    exit 0
}

# ------------------------------------------------------------------- allocate
if ($Action -eq 'allocate') {
    if ([string]::IsNullOrWhiteSpace($RunId)) { Fail 33 '-RunId is required for allocate' }
    $slugList = @()
    if ($null -ne $Slugs) { $slugList = @($Slugs) }
    if ($slugList.Count -eq 0) { Fail 33 '-Slugs is required for allocate (comma-separated, one per worker)' }
    if ($RunId -notmatch '^[A-Za-z0-9._-]+$') {
        Fail 34 ("RunId '" + $RunId + "' must match ^[A-Za-z0-9._-]+$; it becomes part of a branch name")
    }
    if ($slugList.Count -gt $Config.max_workers) {
        Fail 34 ("requested " + $slugList.Count + " workers but max_workers=" + $Config.max_workers)
    }
    $null = Assert-PrimaryCheckout -Code 34
    # Validate every slug before printing any descriptor, so a refusal never
    # follows a partial listing.
    foreach ($slug in $slugList) {
        if ($slug -notmatch '^[A-Za-z0-9._-]+$') {
            Fail 34 ("slug '" + $slug + "' must match ^[A-Za-z0-9._-]+$")
        }
    }

    $i = 0
    foreach ($slug in $slugList) {
        $i++
        if ($slug -notmatch '^[A-Za-z0-9._-]+$') {
            Fail 34 ("slug '" + $slug + "' must match ^[A-Za-z0-9._-]+$")
        }
        $slotName   = $Config.slot_prefix + $i
        $branchName = 'codex/' + $RunId + '/' + $slotName + '-' + $slug
        $exists = Invoke-Git @('-C', $RepoRoot, 'show-ref', '--verify', '--quiet', ('refs/heads/' + $branchName))
        if ($exists.Code -eq 0) { Fail 34 ("branch already exists: " + $branchName) }
        # One object per line. Not an array: 5.1 unwraps single-element arrays,
        # and an ordered hashtable keeps the key order stable.
        $desc = [ordered]@{ slot = $slotName; worktree = (Join-Path $PoolRoot $slotName); branch = $branchName }
        Write-Output (ConvertTo-Json $desc -Compress)
    }
    exit 0
}

# ---------------------------------------------------------------------- reset
if ($Action -eq 'reset') {
    if ([string]::IsNullOrWhiteSpace($Slot))     { Fail 33 '-Slot is required for reset' }
    if ([string]::IsNullOrWhiteSpace($Branch))   { Fail 33 '-Branch is required for reset' }
    if ([string]::IsNullOrWhiteSpace($BaseSha))  { Fail 33 '-BaseSha is required for reset' }
    Assert-Slot -Name $Slot -Code 31

    $wt = Join-Path $PoolRoot $Slot

    $exists = Invoke-Git @('-C', $RepoRoot, 'show-ref', '--verify', '--quiet', ('refs/heads/' + $Branch))
    if ($exists.Code -eq 0) {
        Fail 31 ("branch already exists: " + $Branch)
    }

    $table = Get-WorktreeTable
    $key = Normalize-Path $wt
    $registered = $table.ContainsKey($key)
    $dirPresent = Test-Path -LiteralPath $wt

    if ((-not $registered) -and $dirPresent) {
        Fail 31 ("directory exists but is not a registered worktree: " + $wt + " - inspect it by hand; this script will not delete anything")
    }

    if ($registered) {
        if ($table[$key].Locked) {
            Fail 31 ("worktree is LOCKED: " + $wt + " - a locked worktree holds a deliberate frozen state")
        }
        if ($table[$key].Prunable) {
            Fail 31 ("worktree is marked prunable: " + $wt + " - resolve by hand; this script never prunes")
        }
    }

    if (-not $registered) {
        if (-not (Test-Path -LiteralPath $PoolRoot)) {
            New-Item -ItemType Directory -Path $PoolRoot -Force | Out-Null
        }
        $add = Invoke-Git @('-C', $RepoRoot, 'worktree', 'add', '-b', $Branch, $wt, $BaseSha)
        if ($add.Code -ne 0) { Fail 31 ("worktree add failed: " + $add.Text) }
        Write-Output ("created=" + $wt)
    } else {
        Assert-LinkedWorktree -Path $wt -Code 31

        $dirty = Invoke-Git @('-C', $wt, 'status', '--porcelain')
        if ($dirty.Text.Length -gt 0) {
            $label = 'orch/pre-reset/' + $Slot + '/' + (Get-Date -Format 'yyyyMMdd-HHmmss')
            # A previous round left intent-to-add index entries behind (the
            # worker adds them so new files show up in git diff). stash push
            # refuses to run against those with "not uptodate. Cannot merge",
            # so clear the index first. This is a mixed reset: it touches the
            # index only, never the working tree, so nothing is lost here.
            $unstage = Invoke-Git @('-C', $wt, 'reset', '--quiet')
            if ($unstage.Code -ne 0) { Fail 31 ("could not clear the index: " + $unstage.Text) }
            # -u rescues newly created files too. NOT -a/--all: -u covers
            # untracked, -a would also sweep up ignored paths, and the
            # ecosystem's dependency store and build output are ignored - they
            # are the warm state we keep.
            $stash = Invoke-Git @('-C', $wt, 'stash', 'push', '-u', '-m', $label)
            if ($stash.Code -ne 0) { Fail 31 ("could not stash pre-existing changes: " + $stash.Text) }
            Write-Output ("stashed=" + $label + " (recover with: git -C " + $wt + " stash list)")
        }

        $cur = Invoke-Git @('-C', $wt, 'symbolic-ref', '--quiet', '--short', 'HEAD')
        if ($cur.Code -ne 0) {
            # Detached. If the commits are on no ref, a reset makes them unreachable.
            $head = Invoke-Git @('-C', $wt, 'rev-parse', 'HEAD')
            $refs = Invoke-Git @('-C', $RepoRoot, 'for-each-ref', '--contains', $head.Text, '--format=%(refname)')
            if ($refs.Text.Length -eq 0) {
                Fail 31 ("slot is detached at " + $head.Text + " and those commits are on no branch; resetting would orphan them")
            }
            Write-Output ("was_detached_at=" + $head.Text + " (reachable from: " + ($refs.Text -replace "`n", ' ') + ")")
        } else {
            $ahead = Invoke-Git @('-C', $wt, 'rev-list', '--count', ($BaseSha + '..HEAD'))
            Write-Output ("previous_branch=" + $cur.Text + " ahead=" + $ahead.Text + " (ref kept, nothing lost)")
        }

        $r1 = Invoke-Git @('-C', $wt, 'reset', '--hard')
        if ($r1.Code -ne 0) { Fail 31 ("reset --hard failed: " + $r1.Text) }
        # -fd ONLY. Never -x or -X: ignored paths are the warm build output and
        # dependency store this whole design exists to preserve.
        $r2 = Invoke-Git @('-C', $wt, 'clean', '-fd')
        if ($r2.Code -ne 0) { Fail 31 ("clean -fd failed: " + $r2.Text) }
        # --create, never -C/-B: force-create is exactly what must not happen.
        $r3 = Invoke-Git @('-C', $wt, 'switch', '--create', $Branch, $BaseSha)
        if ($r3.Code -ne 0) { Fail 31 ("switch --create failed: " + $r3.Text) }
        Write-Output ("reset=" + $wt)
    }

    $vHead   = Invoke-Git @('-C', $wt, 'rev-parse', 'HEAD')
    $vBranch = Invoke-Git @('-C', $wt, 'symbolic-ref', '--short', 'HEAD')
    $vStatus = Invoke-Git @('-C', $wt, 'status', '--porcelain')
    if ($vHead.Text -ne $BaseSha)   { Fail 31 ("verify failed: HEAD is " + $vHead.Text) }
    if ($vBranch.Text -ne $Branch)  { Fail 31 ("verify failed: on branch " + $vBranch.Text) }
    if ($vStatus.Text.Length -gt 0) { Fail 31 ("verify failed: worktree is not clean:`n" + $vStatus.Text) }

    # Warm state, derived from the manifests actually in the slot.
    $warm = @()
    foreach ($m in @(Get-Manifests -Dir $wt)) {
        if (-not $m.Root) { continue }
        if ($m.Store.Length -eq 0) { continue }
        $storeRel = $m.Store
        if ($m.Rel.Length -gt 0) { $storeRel = $m.Rel + '/' + $m.Store }
        $warm += ($storeRel + ':' + (Get-DepsPresent $m))
    }
    Write-Output ("slot=" + $Slot + " branch=" + $Branch + " head=" + $BaseSha + " clean=yes")
    if ($warm.Count -gt 0) { Write-Output ("warm=" + ($warm -join ' ')) } else { Write-Output "warm=none" }
    Write-Output "reset=ok"
    exit 0
}

# --------------------------------------------------------------------- commit
if ($Action -eq 'commit') {
    if ([string]::IsNullOrWhiteSpace($Slot))        { Fail 33 '-Slot is required for commit' }
    if ([string]::IsNullOrWhiteSpace($BaseSha))     { Fail 33 '-BaseSha is required for commit' }
    if ([string]::IsNullOrWhiteSpace($MessageFile)) { Fail 33 '-MessageFile is required for commit' }
    Assert-Slot -Name $Slot -Code 32
    if (-not (Test-Path -LiteralPath $MessageFile)) { Fail 33 ('message file not found: ' + $MessageFile) }

    $wt = Join-Path $PoolRoot $Slot
    Assert-LinkedWorktree -Path $wt -Code 32

    $head = Invoke-Git @('-C', $wt, 'rev-parse', 'HEAD')
    if ($head.Text -ne $BaseSha) {
        Fail 32 ("HEAD is " + $head.Text + ", expected base " + $BaseSha + " - the slot already has commits; review before committing again")
    }

    $status = Invoke-Git @('-C', $wt, 'status', '--porcelain')
    if ($status.Text.Length -eq 0) {
        Write-Output "nothing to commit"
        exit 0
    }

    $add = Invoke-Git @('-C', $wt, 'add', '-A')
    if ($add.Code -ne 0) { Fail 32 ("git add failed: " + $add.Text) }

    $commit = Invoke-Git @('-C', $wt, 'commit', '--file', $MessageFile)
    if ($commit.Code -ne 0) { Fail 32 ("git commit failed: " + $commit.Text) }

    $new = Invoke-Git @('-C', $wt, 'rev-parse', 'HEAD')
    $br  = Invoke-Git @('-C', $wt, 'symbolic-ref', '--short', 'HEAD')
    Write-Output ("committed=" + $new.Text + " branch=" + $br.Text)
    Write-Output "commit=ok"
    exit 0
}

Fail 33 ("unknown action: " + $Action)
