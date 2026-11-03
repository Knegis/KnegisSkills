# Offline behavioral checks. No model calls. Windows PowerShell 5.1.
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'worker-policy.ps1')
$script:checks = 0
function Assert-True {
    param([bool] $Condition, [string] $Message)
    if (-not $Condition) { throw $Message }
    $script:checks++
}
function Assert-Throws {
    param([scriptblock] $Action, [string] $Pattern)
    try { $null = & $Action } catch {
        if ($_.Exception.Message -notmatch $Pattern) { throw }
        $script:checks++
        return
    }
    throw ('Expected rejection: ' + $Pattern)
}
function Save-Json {
    param([string] $Path, [object] $Value)
    [IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 8), (New-Object Text.UTF8Encoding($false)))
}
$scratch = Join-Path ([IO.Path]::GetTempPath()) ('worker-policy-test-' + [guid]::NewGuid().ToString('N'))
$repo = Join-Path $scratch 'repo'
$wt = Join-Path $scratch 'pool\worker with spaces'
$allowed = Join-Path $scratch 'approved with spaces'
$other = Join-Path $scratch 'other'
$runDir = Join-Path $scratch 'not-created'
$configFile = Join-Path $scratch 'config.json'
try {
    $null = New-Item -ItemType Directory -Path $scratch, (Split-Path $wt -Parent), $allowed, $other -Force
    & git init -q $repo
    & git -C $repo -c user.name=Fixture -c user.email=fixture@example.invalid commit -qm fixture --allow-empty
    & git -C $repo worktree add -qb fixture $wt
    if ($LASTEXITCODE -ne 0) { throw 'Fixture setup failed' }
    $base = (& git -C $wt rev-parse HEAD).Trim()
    $spec = [pscustomobject]@{
        worker_id = 'worker-1'; run_id = 'fixture'; round = 1; repo_root = $repo; worktree = $wt
        branch = 'fixture'; base_sha = $base; run_dir = $runDir; prompt_file = (Join-Path $scratch 'prompt.txt')
        schema_file = (Join-Path $scratch 'schema.json'); model = 'fixture'; reasoning_effort = 'medium'
        sandbox = 'workspace-write'; timeout_seconds = 5; env = [pscustomobject]@{}
    }
    $config = Get-OrchestratorConfig $configFile
    Assert-True (@(Assert-WorkerPolicy $spec $config).Count -eq 0) 'Default policy must permit no extra directories'
    $spec | Add-Member -NotePropertyName add_dirs -NotePropertyValue @()
    Assert-True (@(Assert-WorkerPolicy $spec $config).Count -eq 0) 'Empty add_dirs rejected'
    foreach ($value in @('read-only', 'danger-full-access', 'WORKSPACE-WRITE', '', 1, $null, @('workspace-write'))) {
        $spec.sandbox = $value
        Assert-Throws { Assert-WorkerPolicy $spec $config } 'sandbox'
    }
    $spec.sandbox = 'workspace-write'
    foreach ($value in @('ultra', 'HIGH', 'unknown', '', 1, $null, @('high'))) {
        $spec.reasoning_effort = $value
        Assert-Throws { Assert-WorkerPolicy $spec $config } 'reasoning_effort'
    }
    foreach ($value in @('low', 'medium', 'high', 'xhigh', 'max')) {
        $spec.reasoning_effort = $value
        $null = Assert-WorkerPolicy $spec $config
        $script:checks++
    }
    $spec.model = 'fixture --sandbox danger-full-access'
    Assert-Throws { Assert-WorkerPolicy $spec $config } 'model'
    $spec.model = 'fixture'
    foreach ($value in @($null, $allowed, 1, [pscustomobject]@{})) {
        $spec.add_dirs = $value
        Assert-Throws { Assert-WorkerPolicy $spec $config } 'array'
    }
    foreach ($value in @('relative', '\\server\share', '\\?\C:\device', 'C:\wild*', (Join-Path $scratch 'missing'), $null, 1)) {
        $spec.add_dirs = @($value)
        Assert-Throws { Assert-WorkerPolicy $spec $config } 'absolute|exist'
    }
    $spec.add_dirs = @($allowed)
    Assert-Throws { Assert-WorkerPolicy $spec $config } 'not approved'
    $config.approved_write_dirs_by_repo[$repo] = @($allowed)
    Assert-True (@(Assert-WorkerPolicy $spec $config)[0] -eq $allowed) 'Approved directory rejected'
    $config.approved_write_dirs_by_repo = @{ $other = @($allowed) }
    Assert-Throws { Assert-WorkerPolicy $spec $config } 'not approved'
    $config.approved_write_dirs_by_repo = @{ $repo = @($allowed) }
    foreach ($path in @($other, (Join-Path $allowed '..\other'))) {
        $spec.add_dirs = @($path)
        Assert-Throws { Assert-WorkerPolicy $spec $config } 'not approved'
    }
    $child = Join-Path $allowed 'child'; $prefix = $allowed + '-collision'
    $null = New-Item -ItemType Directory -Path $child, $prefix
    foreach ($path in @($child, $prefix)) {
        $spec.add_dirs = @($path)
        Assert-Throws { Assert-WorkerPolicy $spec $config } 'not approved'
    }
    foreach ($path in @($repo, (Join-Path $repo '.git'), (Split-Path $wt -Parent), $scratch, (Join-Path $HOME '.claude'), (Join-Path $HOME '.codex'))) {
        $config.approved_write_dirs_by_repo = @{ $repo = @($path) }; $spec.add_dirs = @($path)
        Assert-Throws { Assert-WorkerPolicy $spec $config } 'protected'
    }
    $junction = Join-Path $scratch 'junction'
    $null = New-Item -ItemType Junction -Path $junction -Target $allowed
    try {
        Assert-Throws { Get-PolicyPath $junction } 'Reparse'
        Assert-Throws { Get-PolicyPath (Join-Path $junction 'child') } 'Reparse'
    } finally { [IO.Directory]::Delete($junction) }
    $config.approved_write_dirs_by_repo = @{}; $spec.add_dirs = @()
    foreach ($key in @('CODEX_HOME', 'HOME', 'USERPROFILE', 'CODEX_SANDBOX_POLICY')) {
        $spec.env = [pscustomobject]@{ $key = $other }
        Assert-Throws { Assert-WorkerPolicy $spec $config } 'environment'
    }
    $spec.env = [pscustomobject]@{}
    $originalRepo = $spec.repo_root; $spec.repo_root = $other
    Assert-Throws { Assert-WorkerPolicy $spec $config } 'own'
    $spec.repo_root = $originalRepo
    foreach ($value in @(@{ unknown = 1 }, @{ max_workers = '4' }, @{ max_workers = 1.5 }, @{ run_root = 'relative' }, @{ approved_write_dirs_by_repo = @() }, @{ approved_write_dirs_by_repo = @{ $repo = $allowed } })) {
        Save-Json $configFile $value
        Assert-Throws { Get-OrchestratorConfig $configFile } 'config|must|Invalid|array|absolute'
    }
    Save-Json $configFile @{ approved_write_dirs_by_repo = @{ $repo = @($allowed) } }
    $loaded = Get-OrchestratorConfig $configFile
    Assert-True ($loaded.approved_write_dirs_by_repo[$repo][0] -eq $allowed) 'Allowlist failed JSON roundtrip'
    Save-Json $configFile @{}
    $specFile = Join-Path $scratch 'spec.json'
    $shell = Join-Path $PSHOME 'powershell.exe'
    foreach ($failure in @('sandbox', 'effort', 'directories', 'environment')) {
        $spec.sandbox = 'workspace-write'; $spec.reasoning_effort = 'medium'; $spec.add_dirs = @(); $spec.env = [pscustomobject]@{}
        switch ($failure) {
            sandbox { $spec.sandbox = 'danger-full-access' }
            effort { $spec.reasoning_effort = 'ultra' }
            directories { $spec.add_dirs = @($other) }
            environment { $spec.env = [pscustomobject]@{ CODEX_HOME = $other } }
        }
        Save-Json $specFile $spec
        $output = & $shell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'codex-worker.ps1') -SpecFile $specFile -ConfigFile $configFile -DryRun
        Assert-True ($LASTEXITCODE -eq 10) ('Invalid spec did not exit 10: ' + ($output -join ' '))
        Assert-True (-not (Test-Path -LiteralPath $runDir)) 'Invalid spec created artifacts before rejection'
    }
    $argsText = (Get-WorkerPolicyArgs) -join ' '
    Assert-True ($argsText.Contains('writable_roots=[]') -and $argsText.Contains('network_access=false')) 'Inherited config not overridden'
    $baselineConfig = "sandbox_mode = `"workspace-write`"`n"
    $fixtureRepo = (Join-Path $HOME 'codex-sandbox-probes\20261103-151853-3d915b207de64fc2babde4957e732011\repo').ToLowerInvariant()
    $bookmark = "[projects.'" + $fixtureRepo + "']`ntrust_level = `"trusted`"`n`n"
    Assert-True ((Get-StableSandboxConfig ($baselineConfig + $bookmark)) -eq $baselineConfig) 'Fixture trust bookmark made its own measurement stale'
    Assert-True ((Get-StableSandboxConfig ($baselineConfig + "[windows]`nsandbox = `"elevated`"`n")) -ne $baselineConfig) 'Backend change was ignored'
    Assert-True ((Get-StableSandboxConfig ($baselineConfig + "[projects.'C:\real-project']`ntrust_level = `"trusted`"`n")) -ne $baselineConfig) 'Real project trust change was ignored'
    $cli = [pscustomobject]@{ Source = 'fixture'; Version = 'fixture' }
    $config.run_root = Join-Path $scratch 'evidence-root'
    Assert-True ((Write-SandboxEvidenceWarning $cli $config) -match 'missing') 'Missing evidence did not warn'
    $evidenceDir = Join-Path $config.run_root 'sandbox-evidence'
    $null = New-Item -ItemType Directory -Path $evidenceDir -Force
    $latest = Join-Path $evidenceDir 'latest.json'
    Save-Json $latest @{ fingerprint = 'old'; status = 'passed' }
    Assert-True ((Write-SandboxEvidenceWarning $cli $config) -match 'stale') 'Stale evidence did not warn'
    $fingerprint = Get-SandboxFingerprint $cli $config
    foreach ($state in @('failed', 'inconclusive')) {
        Save-Json $latest @{ fingerprint = $fingerprint; status = $state }
        Assert-True ((Write-SandboxEvidenceWarning $cli $config) -match $state) 'Unverified evidence did not warn'
    }
    Save-Json $latest @{ fingerprint = $fingerprint; status = 'passed' }
    Assert-True ($null -eq (Write-SandboxEvidenceWarning $cli $config)) 'Fresh passing evidence warned'
    $cli.Version = 'upgraded'
    Assert-True ((Write-SandboxEvidenceWarning $cli $config) -match 'stale') 'CLI upgrade did not invalidate evidence'
    Write-Output ('PASS: ' + $script:checks + ' policy/config/path/evidence checks; no model calls')
} finally {
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    $resolved = [IO.Path]::GetFullPath($scratch)
    if (-not $resolved.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe fixture cleanup path' }
    if (Test-Path -LiteralPath $resolved) { Remove-Item -LiteralPath $resolved -Recurse -Force }
}
