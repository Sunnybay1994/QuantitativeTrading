$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $workspace
$env:PYTHONPATH = Join-Path $workspace 'src'
$env:PYTHONUTF8 = '1'
$env:POLARS_MAX_THREADS = '2'
$logs = Join-Path $workspace 'artifacts\baostock_history\scheduler'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$now = Get-Date
# Evening daily observation owns 21:00-22:59 on exchange days. History is resumable next :25.
if ($now.DayOfWeek -notin [DayOfWeek]::Saturday, [DayOfWeek]::Sunday -and $now.Hour -ge 21 -and $now.Hour -lt 23) {
    $defer = Join-Path $logs ('deferred_' + $now.ToString('yyyyMMdd_HHmmss_fffffff') + '.json')
    @{status='deferred'; updated_at=$now.ToString('o'); reason='Evening daily observation window; resume next hourly boundary'} |
        ConvertTo-Json | Set-Content -LiteralPath $defer -Encoding utf8
    exit 0
}
# GP full-context freezes clean bar_intraday bytes; do not rewrite them under an active miner.
$writers = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -match 'quant research (daily|nightly|mining|cycle|gp)|quant\.(research\.(continuous_mining|nightly|run_genetic_factor_search|run_factor_search|run_research_cycle)|data\.(refresh|refresh_minute_factors))' })
if ($writers.Count -gt 0) {
    $defer = Join-Path $logs ('deferred_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fffffff') + '.json')
    @{status='deferred'; updated_at=(Get-Date).ToString('o'); reason='Mining/GP or refresh writer holds frozen bars'; writer_pids=@($writers.ProcessId)} |
        ConvertTo-Json | Set-Content -LiteralPath $defer -Encoding utf8
    exit 0
}
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$log = Join-Path $logs ((Get-Date -Format 'yyyyMMdd_HHmmss_fffffff') + '.log')
& 'D:\Miniforge3\python.exe' -m quant data baostock-history *> $log
exit $LASTEXITCODE
