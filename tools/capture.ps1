# Capture Blaston's web traffic with mitmproxy in "local" mode (intercepts only Blaston.exe; no proxy settings needed).
# Usage:  powershell -ExecutionPolicy Bypass -File tools\capture.ps1 [-Name login-and-match] [-Process Blaston]
# Windows will show a UAC prompt: mitmproxy's local-mode redirector needs admin rights to intercept the game's traffic.
param(
    [string]$Name = (Get-Date -Format "yyyyMMdd-HHmmss"),
    [string]$Process = "Blaston"
)
$root = Split-Path -Parent $PSScriptRoot
$out = Join-Path $root "capture\$Name"
New-Item -ItemType Directory -Force $out | Out-Null
Write-Host "Capturing $Process traffic to $out  (Ctrl+C to stop)"
& "$root\.venv\Scripts\mitmdump.exe" `
    --mode "local:$Process" `
    -s "$root\tools\capture_addon.py" `
    --set "capture_dir=$out" `
    --set stream_large_bodies=50m `
    -w "$out\raw.flows" `
    --flow-detail 1
