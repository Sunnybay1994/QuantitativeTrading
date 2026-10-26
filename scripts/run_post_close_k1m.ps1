param(
    [int]$Limit = 0,
    [double]$MaxSeconds = 7200,
    [int]$MaxBatches = 0,
    [string]$Markets = "",
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $workspace
$env:PYTHONPATH = Join-Path $workspace 'src'
$env:POLARS_MAX_THREADS = '2'
$env:PYTHONUTF8 = '1'
$logRoot = Join-Path $workspace 'artifacts\post_close_k1m\scheduler'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$logFile = Join-Path $logRoot ('post_close_k1m_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fffffff') + '.log')
$python = 'D:\Miniforge3\python.exe'
# Yield while live realtime collector holds OpenD subscriptions, or GP freezes bars.
$blockers = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -match 'quant data realtime|quant\.data\.realtime|quant research (mining|nightly|cycle|gp)|quant\.research\.(continuous_mining|nightly|run_genetic_factor_search)' })
if ($blockers.Count -gt 0) {
    @{status='deferred'; updated_at=(Get-Date).ToString('o'); reason='OpenD/live realtime or mining writer busy'; writer_pids=@($blockers.ProcessId)} |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logRoot 'scheduler.json') -Encoding utf8
    exit 0
}
$argsList = @('-m', 'quant', 'data', 'post-close-k1m')
if ($Limit -gt 0) { $argsList += @('--limit', "$Limit") }
if ($MaxSeconds -gt 0) { $argsList += @('--max-seconds', "$MaxSeconds") }
if ($MaxBatches -gt 0) { $argsList += @('--max-batches', "$MaxBatches") }
if ($Markets) { $argsList += @('--markets', $Markets) }
if ($Force) { $argsList += '--force' }
$ErrorActionPreference = 'Continue'
& $python @argsList 2>&1 | Out-File -LiteralPath $logFile -Append -Encoding utf8
$code = $LASTEXITCODE
@{status='finished'; updated_at=(Get-Date).ToString('o'); exit_code=$code; log=$logFile; markets=$Markets} |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logRoot 'scheduler.json') -Encoding utf8
exit $code
