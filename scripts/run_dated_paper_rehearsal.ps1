$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $workspace
$env:PYTHONPATH = Join-Path $workspace 'src'
$env:PYTHONUTF8 = '1'
$env:POLARS_MAX_THREADS = '2'
$folder = Join-Path $workspace 'artifacts\paper\dated_rehearsal\scheduler'
New-Item -ItemType Directory -Path $folder -Force | Out-Null
$log = Join-Path $folder ((Get-Date -Format 'yyyyMMddTHHmmss_fffffff') + '.log')
$code = 1
try {
    $ErrorActionPreference = 'Continue'
    & 'D:\Miniforge3\python.exe' -m quant.execution.dated_paper_rehearsal 2>&1 | Out-File -LiteralPath $log -Encoding utf8
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = 1 }
} finally {
    $ErrorActionPreference = 'Stop'
    @{observed_at=(Get-Date).ToString('o'); target='2026-11-27'; rehearsal=$true; auto_trade=$false; exit_code=$code; log=$log} |
        ConvertTo-Json | Set-Content -LiteralPath ($log + '.json') -Encoding utf8
}
exit $code
