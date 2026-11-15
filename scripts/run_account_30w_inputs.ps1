$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $workspace
$env:PYTHONPATH = Join-Path $workspace 'src'
$env:PYTHONUTF8 = '1'
$env:POLARS_MAX_THREADS = '2'
$python = 'D:\Miniforge3\python.exe'
$folder = Join-Path $workspace ('artifacts\data\account_30w_prepare\'+(Get-Date -Format 'yyyyMMdd_HHmmss_fffffff'))
$logs = Join-Path $workspace 'artifacts\data\account_30w_prepare\scheduler'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$log = Join-Path $logs ((Get-Date -Format 'yyyyMMdd_HHmmss_fffffff')+'.log')
if (-not (Test-Path -LiteralPath $python)) { throw 'Project Python interpreter missing' }
$ErrorActionPreference = 'Continue'
& $python -m quant data account-30w-inputs --output $folder *> $log
$code = $LASTEXITCODE
& $python -m quant.notify.automation_alert --task 'Account30wInputPreparation' --code $code --log $log *>> $log
exit $code
