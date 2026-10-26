param([switch]$History)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $workspace
$env:PYTHONPATH = Join-Path $workspace 'src'
$env:POLARS_MAX_THREADS = '2'
$env:PYTHONUTF8 = '1'
$kind = if ($History) { 'minute-history' } else { 'minutes' }
$logRoot = Join-Path $workspace 'artifacts\minute_refresh\scheduler'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$logFile = Join-Path $logRoot ($kind + '_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fffffff') + '.log')
$python = 'D:\Miniforge3\python.exe'
function Invoke-LoggedPython([string[]]$PythonArguments) {
    # Windows PowerShell treats native stderr as an ErrorRecord; Stop can abort
    # at the first traceback line. Preserve all output and the native exit code.
    $ErrorActionPreference = 'Continue'
    & $python @PythonArguments 2>&1 | Out-File -LiteralPath $logFile -Append -Encoding utf8
    return $LASTEXITCODE
}
function Invoke-MinuteFactors {
    # This stage publishes factor panels. It must yield to existing daily/model writers.
    $factorWriters = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -match 'quant research (daily|nightly|mining|cycle|gp)|quant data (refresh|minute-factors|minutes|minute-history|baostock-history)|quant\.(data\.(refresh|refresh_minute_factors|intraday|baostock_history|recent_minutes|minute_history)|factors\.compute|research\.(continuous_mining|nightly|run_daily|scheduled_observation|run_factor_search|run_genetic_factor_search|run_research_cycle|run_constrained|run_multifactor)|execution\.(q10_paper|stock_paper|paper_ledger|cross_asset_forward))|daily_recovery.+recover.py' })
    if ($factorWriters.Count -gt 0) {
        @{status='deferred'; updated_at=(Get-Date).ToString('o'); reason='Existing data/factor/account writer'; writer_pids=@($factorWriters.ProcessId)} |
            ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logRoot 'factor_scheduler.json') -Encoding utf8
        # Yielding the factor publish is a successful scheduler outcome.
        exit 0
    }
    # Collection and bounded minute-factor reconciliation have their own receipt.
    # A partial provider response remains partial; it cannot block daily-only signals.
    $factorCode = Invoke-LoggedPython @('-m', 'quant', 'data', 'minute-factors', '--collect')
    @{status='finished'; updated_at=(Get-Date).ToString('o'); exit_code=$factorCode; log=$logFile} |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logRoot 'factor_scheduler.json') -Encoding utf8
    return $factorCode
}
try {
    # Collection rewrites clean bar_intraday; yield while GP freeze is live.
    $miningWriters = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -match 'quant research (mining|nightly|cycle|gp)|quant\.research\.(continuous_mining|nightly|run_genetic_factor_search)' })
    if ($miningWriters.Count -gt 0) {
        @{status='deferred'; updated_at=(Get-Date).ToString('o'); reason='Mining/GP writer holds frozen bars'; writer_pids=@($miningWriters.ProcessId)} |
            ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logRoot 'data_scheduler.json') -Encoding utf8
        exit 0
    }
    $dataCode = Invoke-LoggedPython @('-m', 'quant', 'data', $kind)
    $null = Invoke-LoggedPython @('-m', 'quant.notify.automation_alert', '--task', $kind, '--code', "$dataCode", '--log', $logFile)
    if ($dataCode -ne 0) { exit $dataCode }
    $factorCode = Invoke-MinuteFactors
    $researchCode = Invoke-LoggedPython @('-m', 'quant', 'research', 'minutes')
    $null = Invoke-LoggedPython @('-m', 'quant.notify.automation_alert', '--task', '分钟策略研究', '--code', "$researchCode", '--log', $logFile)
    if ($dataCode -ne 0) { exit $dataCode }
    if ($factorCode -ne 0) { exit $factorCode }
    exit $researchCode
} catch {
    $_.Exception.Message | Out-File $logFile -Append -Encoding utf8
    $null = Invoke-LoggedPython @('-m', 'quant.notify.automation_alert', '--task', $kind, '--code', '1', '--log', $logFile)
    exit 1
}
