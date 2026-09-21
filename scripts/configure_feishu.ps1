param([switch]$Status)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $workspace 'src'
$env:PYTHONUTF8 = '1'
$argsList = @('-m', 'quant.notify.feishu_credentials')
if ($Status) { $argsList += '--status' }
& 'D:\Miniforge3\python.exe' @argsList
exit $LASTEXITCODE
