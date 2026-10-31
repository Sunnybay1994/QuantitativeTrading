param(
    [int]$Limit = 0,
    [double]$MaxSeconds = 7200,
    [int]$MaxBatches = 0,
    [string]$Markets = "",
    [switch]$Force,
    [int]$WriterWaitMinutes = 45
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

# US cash session uses Futu OpenD only. ContinuousMining/GP freezes CN bars, not US K_1M —
# treating mining as a US blocker caused 2026-10-31 06:00 to defer with exit 0 and skip US 10-30.
$usOnly = ($Markets.Trim().ToLower() -eq 'us')
$blockerPattern = if ($usOnly) {
    'quant data realtime|quant\.data\.realtime'
} else {
    'quant data realtime|quant\.data\.realtime|quant research (mining|nightly|cycle|gp)|quant\.research\.(continuous_mining|nightly|run_genetic_factor_search)'
}

function Get-PostCloseBlockers([string]$Pattern) {
    @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -match $Pattern })
}

$deadline = (Get-Date).AddMinutes([Math]::Max(0, $WriterWaitMinutes))
$blockers = Get-PostCloseBlockers $blockerPattern
while ($blockers.Count -gt 0 -and (Get-Date) -lt $deadline) {
    @{status='deferred_waiting'; updated_at=(Get-Date).ToString('o'); reason='writer busy'; markets=$Markets; writer_pids=@($blockers.ProcessId); wait_until=$deadline.ToString('o')} |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logRoot 'scheduler.json') -Encoding utf8
    Start-Sleep -Seconds 60
    $blockers = Get-PostCloseBlockers $blockerPattern
}
if ($blockers.Count -gt 0) {
    @{status='deferred_timeout'; updated_at=(Get-Date).ToString('o'); reason='writer busy'; markets=$Markets; writer_pids=@($blockers.ProcessId); waited_minutes=$WriterWaitMinutes} |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logRoot 'scheduler.json') -Encoding utf8
    exit 2
}

$argsList = @('-m', 'quant', 'data', 'post-close-k1m')
if ($Limit -gt 0) { $argsList += @('--limit', "$Limit") }
if ($MaxSeconds -gt 0) { $argsList += @('--max-seconds', "$MaxSeconds") }
if ($MaxBatches -gt 0) { $argsList += @('--max-batches', "$MaxBatches") }
if ($Markets) { $argsList += @('--markets', "$Markets") }
if ($Force) { $argsList += '--force' }
$ErrorActionPreference = 'Continue'
& $python @argsList 2>&1 | Out-File -LiteralPath $logFile -Append -Encoding utf8
$code = $LASTEXITCODE
@{status='finished'; updated_at=(Get-Date).ToString('o'); exit_code=$code; log=$logFile; markets=$Markets} |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logRoot 'scheduler.json') -Encoding utf8
exit $code
