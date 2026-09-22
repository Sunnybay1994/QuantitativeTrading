param([switch]$History)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $workspace
$env:PYTHONPATH = Join-Path $workspace 'src'
$env:POLARS_MAX_THREADS = '2'
$env:PYTHONUTF8 = '1'
$kind = if ($History) { 'minute-history' } else { 'minutes' }
$logRoot = Join-Path $workspace 'artifacts\minute_refresh\scheduler'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$logFile = Join-Path $logRoot ($kind + '_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fffffff') + '.log')
& 'D:\Miniforge3\python.exe' -m quant data $kind *> $logFile
$dataCode = $LASTEXITCODE
& 'D:\Miniforge3\python.exe' -m quant research minutes *>> $logFile
$researchCode = $LASTEXITCODE
if ($dataCode -ne 0) { exit $dataCode }
exit $researchCode
