# Shared installed-CLI discovery and capability checks. PowerShell 5.1, ASCII.
# Dot-source this file; it does not install, update, or invoke a model.

function Resolve-CodexLauncher {
    # Respect PATH order, including npm's PowerShell shim. Ignore shell aliases
    # and functions: the worker needs a launcher usable by CreateProcess.
    $commands = @(Get-Command 'codex' -All -CommandType Application,ExternalScript -ErrorAction SilentlyContinue)
    if ($commands.Count -eq 0) { throw 'Codex CLI not found on PATH; install it and restart the shell' }
    $source = $commands[0].Source
    $extension = [System.IO.Path]::GetExtension($source)
    if ($extension -eq '.exe') {
        return [pscustomobject]@{ Source = $source; FilePath = $source; PrefixArgs = @(); Kind = 'native' }
    }

    # CreateProcess cannot launch npm's .cmd shim. cmd /c would re-parse TOML
    # quotes, so use the JS entrypoint belonging to this exact PATH installation.
    $installDir = Split-Path $source -Parent
    $entrypoint = Join-Path $installDir 'node_modules\@openai\codex\bin\codex.js'
    if (-not (Test-Path -LiteralPath $entrypoint -PathType Leaf)) {
        throw ("Unsupported Codex launcher: " + $source + '; expected a native .exe or an npm installation')
    }
    $nodePath = Join-Path $installDir 'node.exe'
    if (-not (Test-Path -LiteralPath $nodePath -PathType Leaf)) {
        $node = Get-Command 'node.exe' -CommandType Application -ErrorAction SilentlyContinue
        if ($null -eq $node) { throw ('node.exe not found for npm Codex launcher: ' + $source) }
        $nodePath = $node.Source
    }
    return [pscustomobject]@{
        Source = $source; FilePath = $nodePath
        PrefixArgs = @('"' + $entrypoint + '"'); Kind = 'npm'
    }
}

function Invoke-CodexProbe {
    param([object] $Launcher, [string[]] $ProbeArgs, [int] $TimeoutSeconds = 15)
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $Launcher.FilePath
    $info.Arguments = (@($Launcher.PrefixArgs) + $ProbeArgs) -join ' '
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.RedirectStandardInput = $true
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $info
    try {
        $null = $process.Start()
        $process.StandardInput.Close()
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            # npm launches a child executable; kill the whole probe tree.
            $previousPreference = $ErrorActionPreference
            try {
                $ErrorActionPreference = 'Continue'
                & "$env:SystemRoot\System32\taskkill.exe" /PID $process.Id /T /F 2>&1 | Out-Null
                if (-not $process.HasExited) { $process.Kill() }
                $null = $process.WaitForExit(5000)
            } finally { $ErrorActionPreference = $previousPreference }
            throw ('Codex CLI probe timed out: ' + ($ProbeArgs -join ' '))
        }
        $output = ($stdout.Result + "`n" + $stderr.Result).Trim()
        if ($process.ExitCode -ne 0) {
            throw ('Codex CLI probe failed (' + $process.ExitCode + '): ' + ($ProbeArgs -join ' ') + "`n" + $output)
        }
        return $output
    } finally {
        $process.Dispose()
    }
}

function Get-CodexCli {
    $launcher = Resolve-CodexLauncher
    $version = Invoke-CodexProbe -Launcher $launcher -ProbeArgs @('--version')
    if ([string]::IsNullOrWhiteSpace($version)) { throw 'Codex CLI returned an empty version' }
    $help = Invoke-CodexProbe -Launcher $launcher -ProbeArgs @('exec', '--help')
    $required = @('--cd', '--sandbox', '--config', '--ephemeral', '--color', '--model',
                  '--output-schema', '--output-last-message', '--add-dir')
    $missing = @($required | Where-Object {
        $help -notmatch ('(?m)(?:^|[\s,])' + [regex]::Escape($_) + '(?=[\s,=]|$)')
    })
    if ($missing.Count -gt 0) {
        throw ($version + ' at ' + $launcher.Source + ' lacks required exec flags: ' + ($missing -join ', '))
    }
    $launcher | Add-Member -NotePropertyName Version -NotePropertyValue $version
    return $launcher
}

function Write-CodexCliInfo {
    param([object] $Cli)
    foreach ($key in @('Source', 'FilePath', 'Kind', 'Version')) {
        Write-Output ('codex_' + $key.ToLowerInvariant() + '=' + (ConvertTo-Json $Cli.$key -Compress))
    }
}
