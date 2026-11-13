$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$zone = [TimeZoneInfo]::FindSystemTimeZoneById('China Standard Time')
$now = [TimeZoneInfo]::ConvertTime([DateTimeOffset]::UtcNow, $zone)
# Registering a future task is allowed now; only report execution waits.
if ($now.Date -lt [datetime]'2026-11-23') {
    Write-Output 'Runtime import coverage is not due before 2026-11-23 Asia/Shanghai.'
    exit 2
}
Set-Location -LiteralPath $workspace
$env:PYTHONPATH = Join-Path $workspace 'src'
$env:PYTHONUTF8 = '1'
$env:POLARS_MAX_THREADS = '2'
$folder = Join-Path $workspace 'artifacts\runtime_import_coverage_scheduler'
New-Item -ItemType Directory -Path $folder -Force | Out-Null
$log = Join-Path $folder ((Get-Date -Format 'yyyyMMddTHHmmss_fffffff') + '.log')
$code = 1
try {
    $ErrorActionPreference = 'Continue'
    & 'D:\Miniforge3\python.exe' -m quant report runtime-import-coverage 2>&1 |
        Out-File -LiteralPath $log -Encoding utf8
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = 1 }
} finally {
    $ErrorActionPreference = 'Stop'
    @{observed_at=(Get-Date).ToString('o'); exit_code=$code; log=$log; auto_trade=$false} |
        ConvertTo-Json | Set-Content -LiteralPath ($log + '.json') -Encoding utf8
}
exit $code
