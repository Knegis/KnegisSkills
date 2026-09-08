# render_slides.ps1 - export every slide of a .pptx to PNG via PowerPoint COM.
# This machine has no LibreOffice, so the base pptx skill's thumbnail.py does not work;
# use this instead for the render-QA loop and contact sheets.
# Usage: powershell -File render_slides.ps1 -PptxPath <deck.pptx> -OutDir <dir> [-Width 1920]
#
# Non-disruptive by design (do not regress these):
#   * Renders a TEMP COPY, never the passed file - so a deck you have open is untouched.
#   * Only quits PowerPoint if THIS script started it; if you already had PowerPoint
#     open, it stays open (PowerPoint COM is a single shared instance - quitting it
#     would close your session).
param(
    [Parameter(Mandatory = $true)][string]$PptxPath,
    [Parameter(Mandatory = $true)][string]$OutDir,
    [int]$Width = 1920
)

$PptxPath = (Resolve-Path $PptxPath).Path
New-Item -ItemType Directory -Force $OutDir | Out-Null
$OutDir = (Resolve-Path $OutDir).Path

# Work on a temp copy so we never open (and risk closing) a deck the user has open.
$tmp = Join-Path $env:TEMP ("render_" + [guid]::NewGuid().ToString("N") + ".pptx")
Copy-Item -LiteralPath $PptxPath -Destination $tmp -Force

# Did the user already have PowerPoint running? If so, never quit it.
$preRunning = @(Get-Process -Name POWERPNT -ErrorAction SilentlyContinue).Count -gt 0

$ppt = New-Object -ComObject PowerPoint.Application
try {
    # Open(FileName, ReadOnly, Untitled, WithWindow) - msoTrue=-1, msoFalse=0 (no window = invisible)
    $pres = $ppt.Presentations.Open($tmp, -1, 0, 0)
    try {
        $h = [int]($Width * $pres.PageSetup.SlideHeight / $pres.PageSetup.SlideWidth)
        $count = 0
        foreach ($slide in $pres.Slides) {
            $count++
            $out = Join-Path $OutDir ("slide{0:D2}.png" -f $count)
            $slide.Export($out, "PNG", $Width, $h)
        }
        Write-Output "Exported $count slides to $OutDir"
    }
    finally { $pres.Close() }
}
finally {
    if (-not $preRunning) { try { $ppt.Quit() } catch {} }   # only quit an instance we started
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($ppt) | Out-Null
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
}
