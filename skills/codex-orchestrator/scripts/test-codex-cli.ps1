# Offline regression checks. Run with Windows PowerShell 5.1; no model calls.
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'codex-cli.ps1')

function Assert-True {
    param([bool] $Condition, [string] $Message)
    if (-not $Condition) { throw $Message }
}
function Assert-Throws {
    param([scriptblock] $Action, [string] $Pattern)
    try { & $Action } catch {
        if ($_.Exception.Message -match $Pattern) { return }
        throw
    }
    throw ('Expected failure matching: ' + $Pattern)
}

$originalPath = $env:PATH
$originalMode = $env:CODEX_FIXTURE_MODE
$scratch = Join-Path ([System.IO.Path]::GetTempPath()) ('codex-launcher-test-' + [guid]::NewGuid().ToString('N'))
$nativeDir = Join-Path $scratch 'native with spaces'
$npmDir = Join-Path $scratch 'npm with spaces'
$nodePath = (Get-Command node.exe -CommandType Application).Source
$shell = Join-Path $PSHOME 'powershell.exe'
try {
    $null = New-Item -ItemType Directory -Path $nativeDir, $npmDir -Force
    # A real PE executable exercises CreateProcess without needing a native
    # Codex installation or invoking a model. It also exposes received args.
    $sourceCode = @'
using System;
using System.Text;
public class CodexLauncherFixture {
    public static int Main(string[] args) {
        string mode = Environment.GetEnvironmentVariable("CODEX_FIXTURE_MODE");
        if (mode == "timeout") { System.Threading.Thread.Sleep(30000); return 0; }
        if (mode == "failure") { Console.Error.WriteLine("fixture failure"); return 7; }
        if (args.Length == 1 && args[0] == "--version") {
            Console.WriteLine("codex-cli fixture"); return 0;
        }
        if (args.Length == 2 && args[0] == "exec" && args[1] == "--help") {
            Console.WriteLine("--cd --sandbox --config --ephemeral --color --model --output-last-message --add-dir");
            if (mode != "missing") Console.WriteLine("--output-schema");
            return 0;
        }
        foreach (string arg in args) Console.WriteLine(Convert.ToBase64String(Encoding.UTF8.GetBytes(arg)));
        return 0;
    }
}
'@
    $fixtureSource = Join-Path $scratch 'fixture.cs'
    Set-Content -LiteralPath $fixtureSource -Value $sourceCode -Encoding ASCII
    $compiler = Join-Path ([System.Runtime.InteropServices.RuntimeEnvironment]::GetRuntimeDirectory()) 'csc.exe'
    & $compiler /nologo /target:exe ('/out:' + (Join-Path $nativeDir 'codex.exe')) $fixtureSource
    Assert-True ($LASTEXITCODE -eq 0) 'Fixture compilation failed'
    $env:PATH = $nativeDir
    $env:CODEX_FIXTURE_MODE = ''
    $native = Get-CodexCli
    Assert-True ($native.Kind -eq 'native') 'Native discovery failed without Node on PATH'
    $received = Invoke-CodexProbe $native @('exec', '-C', '"C:\worktree with spaces"', '-c', 'approval_policy="never"')
    $decoded = @($received -split "`n" | ForEach-Object {
        [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_.Trim()))
    })
    Assert-True ($decoded[2] -eq 'C:\worktree with spaces') 'Worktree path was split'
    Assert-True ($decoded[4] -eq 'approval_policy=never') 'Config argument was mangled'
    $env:CODEX_FIXTURE_MODE = 'missing'
    Assert-Throws { Get-CodexCli } 'lacks required exec flags: --output-schema'
    $env:CODEX_FIXTURE_MODE = 'failure'
    Assert-Throws { Get-CodexCli } 'probe failed \(7\)'
    $env:CODEX_FIXTURE_MODE = 'timeout'
    Assert-Throws { Invoke-CodexProbe $native @('--version') -TimeoutSeconds 1 } 'probe timed out'
    $env:CODEX_FIXTURE_MODE = ''

    $entryDir = Join-Path $npmDir 'node_modules\@openai\codex\bin'
    $null = New-Item -ItemType Directory -Path $entryDir -Force
    # Delegate to the offline fixture through a real Node process. Neither
    # launcher can call a model.
    $nativeJson = ConvertTo-Json (Join-Path $nativeDir 'codex.exe') -Compress
    $js = 'const cp = require("child_process"); const r = cp.spawnSync(' + $nativeJson + ', process.argv.slice(2), {encoding:"utf8"}); process.stdout.write(r.stdout || ""); process.stderr.write(r.stderr || ""); process.exit(r.status === null ? 9 : r.status);'
    Set-Content -LiteralPath (Join-Path $entryDir 'codex.js') -Value $js -Encoding ASCII
    Set-Content -LiteralPath (Join-Path $npmDir 'codex.cmd') -Value '@exit /b 99' -Encoding ASCII
    Set-Content -LiteralPath (Join-Path $npmDir 'codex.ps1') -Value 'exit 99' -Encoding ASCII
    Copy-Item -LiteralPath $nodePath -Destination (Join-Path $npmDir 'node.exe')
    $env:PATH = $npmDir + ';' + $nativeDir
    $npm = Get-CodexCli
    Assert-True ($npm.Kind -eq 'npm') 'npm installation did not win PATH order'
    Assert-True ($npm.FilePath -eq (Join-Path $npmDir 'node.exe')) 'Adjacent Node was not selected'
    $env:PATH = $nativeDir + ';' + $npmDir
    Assert-True ((Get-CodexCli).Kind -eq 'native') 'Native installation did not win PATH order'
    Remove-Item -LiteralPath (Join-Path $npmDir 'node.exe')
    $env:PATH = $npmDir + ';' + (Split-Path $nodePath -Parent)
    Assert-True ((Get-CodexCli).FilePath -eq $nodePath) 'Node PATH fallback failed'
    $env:PATH = $npmDir
    Assert-Throws { Get-CodexCli } 'node.exe not found'
    Remove-Item -LiteralPath (Join-Path $entryDir 'codex.js')
    $env:PATH = $npmDir + ';' + $nativeDir
    Assert-Throws { Get-CodexCli } 'Unsupported Codex launcher'
    $env:PATH = $scratch
    Assert-Throws { Get-CodexCli } 'not found on PATH'

    $env:PATH = $originalPath
    $installed = Get-CodexCli
    Write-CodexCliInfo $installed

    # Exercise the real worker guards, env overrides, metadata and lock cleanup
    # against a disposable linked worktree, with no model invocation.
    $repo = Join-Path $scratch 'repo'
    $worktree = Join-Path $scratch 'worker with spaces'
    & git init -q $repo
    if ($LASTEXITCODE -ne 0) { throw 'Fixture git init failed' }
    & git -C $repo -c user.name=Fixture -c user.email=fixture@example.invalid commit -q --allow-empty -m fixture
    if ($LASTEXITCODE -ne 0) { throw 'Fixture commit failed' }
    $base = (& git -C $repo rev-parse HEAD).Trim()
    & git -C $repo worktree add -q -b fixture $worktree
    if ($LASTEXITCODE -ne 0) { throw 'Fixture worktree failed' }
    $prompt = Join-Path $scratch 'prompt.txt'
    $schema = Join-Path $scratch 'schema.json'
    Set-Content -LiteralPath $prompt -Value 'offline fixture' -Encoding ASCII
    Set-Content -LiteralPath $schema -Value '{}' -Encoding ASCII
    $specFile = Join-Path $scratch 'spec.json'
    $spec = @{
        worker_id = 'worker-1'; run_id = 'fixture'; round = 1; repo_root = $repo
        worktree = $worktree; branch = 'fixture'; base_sha = $base; run_dir = $scratch
        prompt_file = $prompt; schema_file = $schema; model = 'fixture'; reasoning_effort = 'medium'
        sandbox = 'workspace-write'; timeout_seconds = 5; env = @{}
    }
    $workerScript = Join-Path $PSScriptRoot 'codex-worker.ps1'
    foreach ($kind in @('native', 'npm')) {
        if ($kind -eq 'native') { $spec.env = @{ PATH = $nativeDir + ';' + $originalPath } }
        else { $spec.env = @{} }
        $spec | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $specFile -Encoding ASCII
        $workerOutput = & $shell -NoProfile -ExecutionPolicy Bypass -File $workerScript -SpecFile $specFile -DryRun
        Assert-True ($LASTEXITCODE -eq 0) ('Worker dry run failed: ' + ($workerOutput -join "`n"))
        $metadata = Get-Content -LiteralPath (Join-Path $scratch 'cli-worker-1.json') -Raw | ConvertFrom-Json
        $expectedKind = $kind
        if ($kind -eq 'npm') { $expectedKind = $installed.Kind }
        Assert-True ($metadata.Kind -eq $expectedKind) 'Worker selected the wrong installation'
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $scratch 'lock-worker-1.lock'))) 'Worker dry run leaked its lock'
    }
    $spec.env = @{ PATH = $nativeDir + ';' + $originalPath; CODEX_FIXTURE_MODE = 'missing' }
    $spec | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $specFile -Encoding ASCII
    $workerOutput = & $shell -NoProfile -ExecutionPolicy Bypass -File $workerScript -SpecFile $specFile -DryRun
    Assert-True ($LASTEXITCODE -eq 13) 'Incompatible worker CLI did not exit 13'
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $scratch 'lock-worker-1.lock'))) 'Failed worker leaked its lock'
    $env:PATH = $nativeDir + ';' + $originalPath
    $env:CODEX_FIXTURE_MODE = 'missing'
    $poolOutput = & $shell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'orch-pool.ps1') -Action preflight -RepoRoot $repo
    Assert-True ($LASTEXITCODE -eq 30) 'Preflight accepted incompatible CLI'
    Assert-True (($poolOutput -join "`n") -match 'lacks required exec flags') 'Preflight omitted diagnostic'
    Write-Output 'PASS: native/npm discovery, PATH precedence, Node selection, quoting, missing CLI/flags, failed probes, timeout, installed CLI, worker dry runs/metadata/locks, and preflight rejection'
} finally {
    $env:PATH = $originalPath
    $env:CODEX_FIXTURE_MODE = $originalMode
    # Delete only the unique test directory created above, after checking its
    # absolute location is a child of the intended temporary directory.
    $tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    $resolved = [System.IO.Path]::GetFullPath($scratch)
    if (-not $resolved.StartsWith($tempRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw ('Unsafe test cleanup path: ' + $resolved)
    }
    if (Test-Path -LiteralPath $resolved) { Remove-Item -LiteralPath $resolved -Recurse -Force -ErrorAction Continue }
}
