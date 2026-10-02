# render_html.ps1 - thin wrapper. The renderer now lives in render_html.py (cross-platform,
# see that file for the browser-selection order and isolation notes). Kept so old docs/commands
# that call this script directly still work.
param([Parameter(Mandatory = $true)][string]$HtmlPath, [Parameter(Mandatory = $true)][string]$OutPath)
python (Join-Path $PSScriptRoot "render_html.py") $HtmlPath $OutPath
exit $LASTEXITCODE
