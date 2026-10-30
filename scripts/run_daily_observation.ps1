param([switch]$CheckOnly, [string]$To, [switch]$WaitForWriter)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $workspace
$env:PYTHONPATH = Join-Path $workspace 'src'
$env:POLARS_MAX_THREADS = '4'
$env:PYTHONUTF8 = '1'
# Scheduled tasks often lack user PATH; doctor --record-tests needs git.
$gitCandidates = @(
    'D:\Miniforge3\Library\mingw64\bin',
    'D:\Miniforge3\Library\bin',
    'C:\Program Files\Git\cmd',
    'C:\Program Files\Git\bin'
)
foreach ($g in $gitCandidates) {
    if ((Test-Path -LiteralPath (Join-Path $g 'git.exe')) -and ($env:Path -notlike ("*$g*"))) {
        $env:Path = "$g;" + $env:Path
        break
    }
}
$python = 'D:\Miniforge3\python.exe'
$logRoot = Join-Path $workspace 'artifacts\daily\scheduler'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$logFile = Join-Path $logRoot ((Get-Date -Format 'yyyy-MM-dd_HHmmss_fffffff') + '.log')
# Pin the evening target before diagnostics or suspension can cross midnight.
$requestedDate = $To
if (-not $requestedDate -and (Get-Date).Hour -ge 17) { $requestedDate = Get-Date -Format 'yyyy-MM-dd' }
function Write-Stage([string]$stage) {
    ((Get-Date).ToString('o') + ' ' + $stage) | Out-File $logFile -Append -Encoding utf8
}
function Invoke-Python([string[]]$ArgumentList, [switch]$Append) {
    # Native stderr must not become a terminating error. Otherwise the first
    # traceback line aborts the script and the scheduled task loses the rest.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $python @ArgumentList 2>&1 | Out-File -FilePath $logFile -Encoding utf8 -Append:$Append
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
    if (-not $CheckOnly -and -not $requestedDate -and (Get-Date).Hour -lt 12) {
        Write-Stage 'market_context'
        $code = Invoke-Python @('-m', 'quant.research.daily_market_context') -Append
        Notify-Failure $code
        exit $code
    }
    if (-not $CheckOnly) {
        $waitDeadline = (Get-Date).AddHours(2)
        do {
        $writers = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
            Where-Object { $_.CommandLine -match 'quant research (daily|nightly|mining|cycle|gp)|quant data (refresh|minute-factors|baostock-history)|quant\.(data\.(refresh|refresh_minute_factors|intraday|baostock_history)|factors\.compute|research\.(continuous_mining|run_daily|scheduled_observation|run_factor_search|run_research_cycle|nightly|run_genetic_factor_search|run_constrained_portfolio|run_multifactor)|execution\.(stock_paper|q10_paper|paper_ledger|cross_asset_forward))' })
        if ($writers.Count -gt 0) {
            Write-Stage ('waiting_writer target=' + $requestedDate + ' pids=' + ($writers.ProcessId -join ','))
            # 17:30 only defers to the 21:30 slot when Q10 waits for execution inputs.
            # Exiting 2 here made LastTaskResult look like a failure.
            if (-not $WaitForWriter -and (Get-Date).Hour -ge 17 -and (Get-Date).Hour -lt 21) {
                Write-Stage 'deferred_writer_until_evening'
                exit 0
            }
            if (-not $WaitForWriter -or (Get-Date) -ge $waitDeadline) { exit 2 }
            Start-Sleep -Seconds 30
        }
        } while ($writers.Count -gt 0)
    }
    $runArgs = @('-m', 'quant', 'research', 'daily')
    if ($CheckOnly) { $runArgs += '--check-only' }
    if ($requestedDate) { $runArgs += @('--to', $requestedDate) }
    Write-Stage ('daily target=' + $requestedDate)
    $code = Invoke-Python $runArgs -Append
    if ($code -ne 2) { Notify-Failure $code }
    # Keep the daily failure code; a failed fast suite must also fail the task.
    # Doctor page first: --record-tests alone never writes artifacts/doctor, and an
    # unbounded pytest previously held the task past ExecutionTimeLimit (267014).
    Write-Stage ('daily_exit=' + $code + ' doctor')
    Invoke-Python @('-m', 'quant', 'doctor', '--json', '--no-notify') -Append | Out-Null
    Write-Stage 'doctor_record_tests_bounded'
    $testCode = Invoke-Python @('-m', 'quant', 'doctor', '--record-tests') -Append
    Write-Stage ('doctor_record_tests_exit=' + $testCode + ' doctor_refresh')
    Invoke-Python @('-m', 'quant', 'doctor', '--json', '--no-notify') -Append | Out-Null
    if ($code -eq 0 -and $testCode -ne 0) {
        Notify-Failure $testCode
        exit $testCode
    }
    exit $code
} catch {
    $_.Exception.Message | Out-File $logFile -Append -Encoding utf8
    Notify-Failure 1
    exit 1
}
