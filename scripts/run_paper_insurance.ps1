param([ValidateSet('Watch', 'Rehearse')][string]$Mode = 'Watch')
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $workspace
$env:PYTHONPATH = Join-Path $workspace 'src'
$env:POLARS_MAX_THREADS = '4'
$env:PYTHONUTF8 = '1'
$folder = Join-Path $workspace 'artifacts\paper\insurance_scheduler'
New-Item -ItemType Directory -Path $folder -Force | Out-Null
$log = Join-Path $folder ((Get-Date -Format 'yyyy-MM-dd_HHmmss_fffffff') + '_' + $Mode + '.log')
$arguments = @('-m', 'quant', 'paper')
if ($Mode -eq 'Rehearse') {
    $arguments += @('rehearse', '--as-month-end')
} else {
    $arguments += @('order-watch', '--notify')
}
$ErrorActionPreference = 'Continue'
& 'D:\Miniforge3\python.exe' @arguments 2>&1 | Out-File -LiteralPath $log -Encoding utf8
$code = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
@{mode=$Mode; recorded_at=(Get-Date).ToString('o'); exit_code=$code; log=$log} |
    ConvertTo-Json | Set-Content -LiteralPath ($log + '.json') -Encoding utf8
if ($code -ne 0 -and $Mode -eq 'Rehearse') {
    & 'D:\Miniforge3\python.exe' -m quant.notify.automation_alert --task '月末隔离预演' --code $code --log $log
}
exit $code
