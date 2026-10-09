# Register Sunday 20:00 Intel weekly scan (C1). Requires elevation for schtasks.
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$script = Join-Path $PSScriptRoot 'run_intel_weekly.ps1'
$task = 'QuantitativeTrading-IntelWeekly'
$action = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$script`""
schtasks /Create /F /TN $task /TR $action /SC WEEKLY /D SUN /ST 20:00 /RL LIMITED
Write-Host "Registered $task -> $script"
