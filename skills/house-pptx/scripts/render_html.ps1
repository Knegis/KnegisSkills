# render_html.ps1 - render an HTML slide to PNG at 2x via headless Edge.
# Use this in the design/self-critique loop BEFORE extracting geometry: you cannot see a browser,
# so this PNG is how you look at your own work.
#
# Usage: powershell -File render_html.ps1 -HtmlPath <slide.html> -OutPath <out.png>
#
# Uses an ISOLATED Edge profile per run. A shared profile intermittently lands on a first-run /
# privacy interstitial and screenshots that instead of the slide - which looks like a broken slide
# and wastes a debugging cycle. Also strips a UTF-8 BOM, which otherwise leaks a stray glyph into
# the rendered page.
param(
    [Parameter(Mandatory=$true)][string]$HtmlPath,
    [Parameter(Mandatory=$true)][string]$OutPath
)

$edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if (-not (Test-Path $edge)) { $edge = "C:\Program Files\Microsoft\Edge\Application\msedge.exe" }
if (-not (Test-Path $edge)) { Write-Output "FAILED: Microsoft Edge not found"; exit 1 }

$HtmlPath = (Resolve-Path $HtmlPath).Path
# Edge resolves --screenshot relative to ITS working directory, not ours, so make OutPath absolute
$OutPath = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine((Get-Location).Path, $OutPath))
New-Item -ItemType Directory -Force (Split-Path $OutPath) | Out-Null

# strip a UTF-8 BOM if present
$bytes = [System.IO.File]::ReadAllBytes($HtmlPath)
if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
    [System.IO.File]::WriteAllBytes($HtmlPath, $bytes[3..($bytes.Length - 1)])
    Write-Output "stripped BOM from $HtmlPath"
}

if (Test-Path $OutPath) { Remove-Item $OutPath -Force }   # so a stale PNG can't look like success

$udd = Join-Path $env:TEMP ("edge_slide_" + [System.IO.Path]::GetRandomFileName().Substring(0,8))
$args = @(
    "--headless", "--disable-gpu", "--no-sandbox", "--no-first-run", "--no-default-browser-check",
    "--user-data-dir=$udd", "--force-device-scale-factor=2", "--window-size=1280,720",
    "--default-background-color=FFFFFFFF", "--screenshot=$OutPath", $HtmlPath
)
$p = Start-Process -FilePath $edge -ArgumentList $args -PassThru -WindowStyle Hidden
# headless Edge occasionally hangs on exit with the PNG already written - don't wait forever
if (-not $p.WaitForExit(90000)) { try { $p.Kill() } catch {} }

Remove-Item $udd -Recurse -Force -ErrorAction SilentlyContinue

if (Test-Path $OutPath) {
    $kb = [math]::Round((Get-Item $OutPath).Length / 1KB)
    if ($kb -lt 20) {
        Write-Output "rendered $OutPath ($kb KB) - SUSPICIOUS: too small to be a real slide, open and check it"
    } else {
        Write-Output "rendered $OutPath ($kb KB)"
    }
} else {
    Write-Output "FAILED to render $OutPath"
    exit 1
}
