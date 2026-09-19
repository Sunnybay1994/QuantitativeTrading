param([switch]$Probe)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $workspace
$env:PYTHONPATH = Join-Path $workspace 'src'
$env:POLARS_MAX_THREADS = '2'
$env:PYTHONUTF8 = '1'
$logRoot = Join-Path $workspace 'artifacts/realtime/futu/scheduler'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$logFile = Join-Path $logRoot ((Get-Date -Format 'yyyy-MM-dd_HHmmss_fffffff') + '.log')
$action = if ($Probe) { 'probe' } else { 'run' }
& 'D:\Miniforge3\python.exe' -m quant data realtime $action *> $logFile
exit $LASTEXITCODE
