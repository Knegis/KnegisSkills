# Explicit measurement only: native checks plus one bounded model worker.
[CmdletBinding()]
param(
    [string] $ConfigFile = (Join-Path $HOME '.claude\codex-orchestrator.json'),
    [string] $Model = 'gpt-6-luna',
    [switch] $SkipWorker
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'codex-cli.ps1')
. (Join-Path $PSScriptRoot 'worker-policy.ps1')
try {
    $config = Get-OrchestratorConfig $ConfigFile
    $cli = Get-CodexCli
    $root = Join-Path $config.run_root ('sandbox-evidence\' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N'))
    $null = New-Item -ItemType Directory -Path $root -Force
    $metadata = Join-Path $root 'launcher.json'
    @{ cli = $cli; fingerprint = (Get-SandboxFingerprint $cli $config); os = [Environment]::OSVersion.VersionString } |
        ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $metadata -Encoding UTF8
    $arguments = @((Join-Path $PSScriptRoot 'measure-sandbox.py'), '--root', $root, '--launcher', $metadata, '--model', $Model)
    if ($SkipWorker) { $arguments += '--skip-worker' }
    & python.exe @arguments
    exit $LASTEXITCODE
} catch {
    Write-Error $_.Exception.Message -ErrorAction Continue
    exit 1
}
