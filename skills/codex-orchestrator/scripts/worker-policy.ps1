# Shared worker policy and evidence checks. Windows PowerShell 5.1, ASCII.
function Get-PolicyPath {
    param([object] $Path)
    if ($Path -isnot [string] -or [string]::IsNullOrWhiteSpace($Path) -or
        $Path -notmatch '^[A-Za-z]:[\\/]' -or $Path -match '[*?]' -or $Path.Substring(2).Contains(':')) {
        throw 'Expected an absolute local directory path (no wildcards, UNC or device paths)'
    }
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    if (-not (Test-Path -LiteralPath $full -PathType Container)) { throw ('Directory does not exist: ' + $full) }
    $cursor = Get-Item -LiteralPath $full -Force
    while ($null -ne $cursor) {
        if (($cursor.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw ('Reparse point in path: ' + $cursor.FullName) }
        $cursor = $cursor.Parent
    }
    return $full
}

function Test-PolicyOverlap {
    param([string] $Left, [string] $Right)
    $a = [IO.Path]::GetFullPath($Left).TrimEnd('\', '/') + '\'
    $b = [IO.Path]::GetFullPath($Right).TrimEnd('\', '/') + '\'
    return ($a.StartsWith($b, [StringComparison]::OrdinalIgnoreCase) -or $b.StartsWith($a, [StringComparison]::OrdinalIgnoreCase))
}

function Get-OrchestratorConfig {
    param([string] $ConfigFile = (Join-Path $HOME '.claude\codex-orchestrator.json'))
    $result = [ordered]@{
        slot_prefix = 'worker-'; max_workers = 4; min_free_gb = 10
        run_root = (Join-Path $HOME '.claude\orch-runs'); pool_root_suffix = '-worktrees'
        approved_write_dirs_by_repo = @{}
    }
    if (-not (Test-Path -LiteralPath $ConfigFile)) { return $result }
    $user = Get-Content -LiteralPath $ConfigFile -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($null -eq $user -or $user -isnot [pscustomobject]) { throw 'Config must be a JSON object' }
    foreach ($property in @($user.PSObject.Properties)) {
        $key = $property.Name
        if (-not $result.Contains($key)) { throw ('Unknown config key: ' + $key) }
        $value = $user.$key
        if ($key -eq 'approved_write_dirs_by_repo') {
            if ($value -isnot [pscustomobject]) { throw 'approved_write_dirs_by_repo must be an object' }
            $map = @{}
            foreach ($entry in $value.PSObject.Properties) {
                $repo = Get-PolicyPath $entry.Name
                if ($map.ContainsKey($repo)) { throw ('Duplicate canonical repository: ' + $repo) }
                if ($entry.Value -isnot [array]) { throw 'Approved directories must be a JSON array' }
                $paths = @($entry.Value | ForEach-Object { Get-PolicyPath $_ })
                $map[$repo] = $paths
            }
            $result[$key] = $map
        } elseif ($key -in @('max_workers', 'min_free_gb')) {
            if ($value -isnot [int] -and $value -isnot [long] -and $value -isnot [double] -and $value -isnot [decimal]) { throw ($key + ' must be a number') }
            if ([math]::Floor($value) -ne $value -or $value -lt 0 -or ($key -eq 'max_workers' -and $value -lt 1) -or $value -gt [int]::MaxValue) { throw ('Invalid ' + $key) }
            $result[$key] = [int]$value
        } else {
            if ($value -isnot [string] -or [string]::IsNullOrWhiteSpace($value)) { throw ('Invalid ' + $key) }
            $result[$key] = $value
        }
    }
    if ($result.run_root.StartsWith('~')) { $result.run_root = Join-Path $HOME $result.run_root.Substring(1).TrimStart('/', '\') }
    if (-not [IO.Path]::IsPathRooted($result.run_root)) { throw 'run_root must be absolute' }
    return $result
}

function Get-PolicyGitCommon {
    param([string] $Path)
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $text = & git -C $Path rev-parse --path-format=absolute --git-common-dir 2>$null
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previous }
    if ($code -ne 0) { throw 'Cannot resolve Git ownership for directory' }
    return [IO.Path]::GetFullPath([string]$text)
}

function Assert-WorkerPolicy {
    param([object] $Spec, [object] $Config, [string] $ConfigFile = (Join-Path $HOME '.claude\codex-orchestrator.json'))
    if ($Spec.sandbox -isnot [string] -or $Spec.sandbox -cne 'workspace-write') { throw 'sandbox must be exactly workspace-write' }
    if ($Spec.reasoning_effort -isnot [string] -or $Spec.reasoning_effort -cnotin @('low', 'medium', 'high', 'xhigh', 'max')) { throw 'reasoning_effort must be low, medium, high, xhigh or max; ultra is prohibited' }
    if ($Spec.model -isnot [string] -or $Spec.model -notmatch '^[A-Za-z0-9][A-Za-z0-9._:/-]*$') { throw 'model must be a single model identifier, not command-line arguments' }
    $requested = @()
    if ($Spec.PSObject.Properties.Name -contains 'add_dirs') {
        if ($Spec.add_dirs -isnot [array]) { throw 'add_dirs must be an array' }
        $requested = @($Spec.add_dirs | ForEach-Object { Get-PolicyPath $_ })
    }
    $repo = Get-PolicyPath $Spec.repo_root
    $wt = Get-PolicyPath $Spec.worktree
    $common = Get-PolicyGitCommon $wt
    $repoCommon = Get-PolicyGitCommon $repo
    if (-not [string]::Equals($common, $repoCommon, [StringComparison]::OrdinalIgnoreCase)) { throw 'repo_root does not own the worker worktree' }
    $primary = Split-Path ([string]$common) -Parent
    if (-not [string]::Equals($repo, [IO.Path]::GetFullPath($primary).TrimEnd('\', '/'), [StringComparison]::OrdinalIgnoreCase)) { throw 'repo_root must identify the primary repository' }
    $protected = @($repo, (Split-Path $wt -Parent), $Config.run_root, $Spec.run_dir,
        ([string]$common), (Split-Path ([IO.Path]::GetFullPath($ConfigFile)) -Parent),
        (Join-Path $HOME '.claude'), (Join-Path $HOME '.codex'), (Join-Path $HOME '.agents'), (Join-Path $HOME '.aws'))
    if ($env:CODEX_HOME) { $protected += $env:CODEX_HOME }
    $approved = @()
    if ($Config.approved_write_dirs_by_repo.ContainsKey($repo)) { $approved = @($Config.approved_write_dirs_by_repo[$repo]) }
    foreach ($dir in @($approved + $requested)) {
        foreach ($block in $protected) {
            if (Test-PolicyOverlap $dir $block) { throw ('Writable directory overlaps protected storage: ' + $dir) }
        }
    }
    foreach ($dir in $requested) {
        if ($approved -notcontains $dir) { throw ('Writable directory is not approved for this repository: ' + $dir) }
    }
    # Environment may select a CLI but cannot redirect its security configuration.
    if ($Spec.PSObject.Properties.Name -contains 'env') {
        if ($Spec.env -isnot [pscustomobject]) { throw 'env must be an object' }
        foreach ($property in @($Spec.env.PSObject.Properties)) {
            $key = $property.Name
            if ($key -match '^(CODEX_HOME|HOME|USERPROFILE|CLAUDE_CONFIG_DIR|CODEX_.*(SANDBOX|APPROVAL|PERMISSION).*)$') { throw ('Security environment override prohibited: ' + $key) }
        }
    }
    return @($requested | Select-Object -Unique)
}

function Get-WorkerPolicyArgs {
    # Replace inherited roots; only validated --add-dir grants may extend cwd.
    return @('-c', 'sandbox_workspace_write.writable_roots=[]', '-c', 'sandbox_workspace_write.network_access=false')
}

function Get-StableSandboxConfig {
    param([string] $Text)
    # The installed CLI auto-registers a trust bookmark for each fresh fixture.
    # Ignore only that exact generated table; retain every real-project rule and
    # any other setting. Otherwise every successful probe invalidates itself.
    $prefix = [regex]::Escape((Join-Path $HOME 'codex-sandbox-probes').ToLowerInvariant())
    $pattern = '(?im)^\[projects\.''' + $prefix + '\\[0-9]{8}-[0-9]{6}-[0-9a-f]{32}\\repo''\]\r?\ntrust_level = "trusted"\r?\n(?:\r?\n)?'
    return [regex]::Replace($Text, $pattern, '').Replace("`r`n", "`n")
}

function Get-SandboxFingerprint {
    param([object] $Cli, [object] $Config)
    $files = @('worker-policy.ps1', 'codex-worker.ps1', 'measure-sandbox.py', 'measure-sandbox.ps1')
    $parts = @($Cli.Source, $Cli.Version, [Environment]::OSVersion.VersionString)
    if ($Cli.PSObject.Properties.Name -contains 'FilePath') { $parts += $Cli.FilePath }
    if ($null -ne $Config) {
        foreach ($repo in @($Config.approved_write_dirs_by_repo.Keys | Sort-Object)) {
            $parts += $repo.ToLowerInvariant()
            $parts += @($Config.approved_write_dirs_by_repo[$repo] | Sort-Object | ForEach-Object { $_.ToLowerInvariant() })
        }
    }
    foreach ($file in $files) { $parts += (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $file) -Algorithm SHA256).Hash }
    $codexConfigPath = Join-Path $HOME '.codex\config.toml'
    if ($env:CODEX_HOME) { $codexConfigPath = Join-Path $env:CODEX_HOME 'config.toml' }
    if (Test-Path -LiteralPath $codexConfigPath) { $parts += Get-StableSandboxConfig ([IO.File]::ReadAllText($codexConfigPath)) }
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes(($parts -join "`n"))))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
}

function Write-SandboxEvidenceWarning {
    param([object] $Cli, [object] $Config)
    $path = Join-Path $Config.run_root 'sandbox-evidence\latest.json'
    try {
        if (-not (Test-Path -LiteralPath $path)) { throw 'missing evidence' }
        $record = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($record.fingerprint -ne (Get-SandboxFingerprint $Cli $Config)) { throw 'stale evidence (CLI, OS, config or harness changed)' }
        if ($record.status -ne 'passed') { throw ('measurement is ' + $record.status) }
    } catch {
        Write-Output ('WARN: sandbox evidence: ' + $_.Exception.Message + '; continuing by policy. Run scripts/measure-sandbox.ps1 explicitly.')
    }
}
