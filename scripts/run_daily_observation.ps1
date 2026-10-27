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
function Invoke-Python([string[]]$ArgumentList, [switch]$Append) {
    # Native stderr must not become a terminating error. Otherwise the first
    # traceback line aborts the script and the scheduled task loses the rest.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($Append) { & $python @ArgumentList *>> $logFile } else { & $python @ArgumentList *> $logFile }
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
}
function Notify-Failure([int]$code) {
    if (-not $CheckOnly) { Invoke-Python @('-m', 'quant.notify.automation_alert', '--task', '日更流程', '--code', "$code", '--log', $logFile) -Append | Out-Null }
}
try {
    # Read-only prior-session context has its own lock and source-change guard;
    # it does not need the account/factor writer slot used by the evening run.
    if (-not $CheckOnly -and (Get-Date).Hour -lt 12) {
        $code = Invoke-Python @('-m', 'quant.research.daily_market_context')
        Notify-Failure $code
        exit $code
    }
    if (-not $CheckOnly) {
        # Fast-test receipt for quant doctor. Failure is recorded, not a trading gate.
        Invoke-Python @('-m', 'quant', 'doctor', '--record-tests') -Append | Out-Null
        $writers = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
            Where-Object { $_.CommandLine -match 'quant research (daily|nightly|mining|cycle|gp)|quant data (refresh|minute-factors)|quant\.(data\.(refresh|refresh_minute_factors|intraday)|factors\.compute|research\.(continuous_mining|run_daily|scheduled_observation|run_factor_search|run_research_cycle|nightly|run_genetic_factor_search|run_constrained_portfolio|run_multifactor)|execution\.(stock_paper|q10_paper|paper_ledger|cross_asset_forward))' })
        if ($writers.Count -gt 0) {
            'Deferred: another data/factor/account writer is running.' | Out-File $logFile -Encoding utf8
            exit 2
        }
    }
    $runArgs = @('-m', 'quant', 'research', 'daily')
    if ($CheckOnly) { $runArgs += '--check-only' }
    $code = Invoke-Python $runArgs
    if ($code -ne 2) { Notify-Failure $code }
    # Read-only acceptance page after the 17:30/21:30 run. Do not change the task result.
    Invoke-Python @('-m', 'quant', 'doctor', '--json') -Append | Out-Null
    exit $code
} catch {
    $_.Exception.Message | Out-File $logFile -Append -Encoding utf8
    Notify-Failure 1
    exit 1
}
