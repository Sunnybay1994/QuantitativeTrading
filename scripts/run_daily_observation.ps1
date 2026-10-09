param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $workspace
$env:PYTHONPATH = Join-Path $workspace 'src'
$env:POLARS_MAX_THREADS = '4'
$env:PYTHONUTF8 = '1'
$python = 'D:\Miniforge3\python.exe'
$logRoot = Join-Path $workspace 'artifacts\daily\scheduler'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$logFile = Join-Path $logRoot ((Get-Date -Format 'yyyy-MM-dd_HHmmss_fffffff') + '.log')
function Notify-Failure([int]$code) {
    if (-not $CheckOnly) { & $python -m quant.notify.automation_alert --task '日更流程' --code $code --log $logFile *>> $logFile }
}
try {
    # Read-only prior-session context has its own lock and source-change guard;
    # it does not need the account/factor writer slot used by the evening run.
    if (-not $CheckOnly -and (Get-Date).Hour -lt 12) {
        & $python -m quant.research.daily_market_context *> $logFile
        $code = $LASTEXITCODE
        Notify-Failure $code
        exit $code
    }
    if (-not $CheckOnly) {
        $writers = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
            Where-Object { $_.CommandLine -match 'quant research (daily|nightly|mining|cycle|gp)|quant data (refresh|minute-factors)|quant\.(data\.(refresh|refresh_minute_factors|intraday)|factors\.compute|research\.(continuous_mining|run_daily|scheduled_observation|run_factor_search|run_research_cycle|nightly|run_genetic_factor_search|run_constrained_portfolio|run_multifactor)|execution\.(stock_paper|q10_paper|paper_ledger|cross_asset_forward))' })
        if ($writers.Count -gt 0) {
            'Deferred: another data/factor/account writer is running.' | Out-File $logFile -Encoding utf8
            exit 2
        }
    }
    $runArgs = @('-m', 'quant', 'research', 'daily')
    if ($CheckOnly) { $runArgs += '--check-only' }
    & $python @runArgs *> $logFile
    $code = $LASTEXITCODE
    if ($code -ne 2) { Notify-Failure $code }
    exit $code
} catch {
    $_.Exception.Message | Out-File $logFile -Append -Encoding utf8
    Notify-Failure 1
    exit 1
}
