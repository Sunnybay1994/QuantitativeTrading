$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $workspace
$env:PYTHONPATH = Join-Path $workspace 'src'
$env:PYTHONUTF8 = '1'
$env:POLARS_MAX_THREADS = '2'
$logs = Join-Path $workspace 'artifacts\baostock_history\scheduler'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$log = Join-Path $logs ((Get-Date -Format 'yyyyMMdd_HHmmss_fffffff') + '.log')
& 'D:\Miniforge3\python.exe' -m quant data baostock-history *> $log
exit $LASTEXITCODE
