param([switch]$CheckOnly, [string]$To, [switch]$WaitForWriter, [ValidateRange(0,480)][int]$WriterWaitSeconds=480)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $workspace
$env:PYTHONPATH = Join-Path $workspace 'src'
$env:POLARS_MAX_THREADS = '4'
$env:PYTHONUTF8 = '1'
$env:QUANT_BACKGROUND_WRITER = '0'
$pauseRequestId = $null
$pauseAttempted = $false
# Scheduled tasks often lack the diagnostic tool PATH.
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
        Write-Stage 'account_30w_manual_rehearsal_notification'
        $notifyCode = Invoke-Python @('-m','quant','paper','account-30w-top15','--notify-due') -Append
        Write-Stage ('account_30w_notification_exit=' + $notifyCode)
        Write-Stage 'market_context'
        $code = Invoke-Python @('-m', 'quant.research.daily_market_context') -Append
        if ($code -eq 0 -and $notifyCode -ne 0) { $code = $notifyCode }
        Notify-Failure $code
        exit $code
    }
    if (-not $CheckOnly) {
        $capitalTimer = [Diagnostics.Stopwatch]::StartNew()
        $waitDeadline = (Get-Date).AddSeconds($WriterWaitSeconds)
        do {
        $writers = @(Get-CimInstance Win32_Process -OperationTimeoutSec 5 -Filter "Name='python.exe' OR Name='pythonw.exe'" |
            Where-Object { $_.CommandLine -match 'quant paper (q10|top15-observation|account-30w-top15|order-chain)|quant research (daily|nightly|mining|cycle|gp)|quant data (refresh|minute-factors|baostock-history)|quant\.(data\.(refresh|refresh_minute_factors|intraday|baostock_history)|factors\.compute|research\.(continuous_mining|run_daily|scheduled_observation|run_factor_search|run_research_cycle|nightly|run_genetic_factor_search|run_constrained_portfolio|run_multifactor)|execution\.(stock_paper|q10_paper|paper_ledger|cross_asset_forward|top15_paper|account_30w[^)]*))' })
        if ($writers.Count -gt 0) {
            $accountWriters = @($writers | Where-Object { $_.CommandLine -match 'quant paper|quant\.execution\.(stock_paper|q10_paper|paper_ledger|cross_asset_forward|top15_paper|account_30w)' })
            Write-Stage ('waiting_writer target=' + $requestedDate + ' pids=' + ($writers.ProcessId -join ','))
            # 17:30 only defers to the 21:30 slot when Q10 waits for execution inputs.
            # Exiting 2 here made LastTaskResult look like a failure.
            if (-not $WaitForWriter -and (Get-Date).Hour -ge 17 -and (Get-Date).Hour -lt 21) {
                Write-Stage 'deferred_writer_until_evening'
                exit 0
            }
            if (-not $pauseAttempted) {
                $pauseAttempted = $true
                $previousPreference = $ErrorActionPreference
                try {
                    $ErrorActionPreference = 'Continue'
                    $pauseText = & $python -m quant.core.capital_window request --to $requestedDate 2>> $logFile
                    $pauseCode = $LASTEXITCODE
                    $ErrorActionPreference = 'Stop'
                    if ($pauseCode -ne 0) { throw 'Cooperative pause request unavailable' }
                    $pauseRequest = $pauseText | ConvertFrom-Json
                    if (-not $pauseRequest.request_id) { throw 'Cooperative pause request has no identity' }
                    $pauseRequestId = $pauseRequest.request_id
                    Write-Stage ('capital_pause_requested id=' + $pauseRequestId)
                } catch {
                    Write-Stage 'capital_pause_request_failed; bounded wait and frozen fallback retained'
                } finally { $ErrorActionPreference = $previousPreference }
            }
            if (-not $WaitForWriter -or (Get-Date) -ge $waitDeadline) {
                Write-Stage 'writer_wait_budget_exhausted; frozen_order_fallback'
                $remainingBudget = [Math]::Min(110,[Math]::Floor(590-$capitalTimer.Elapsed.TotalSeconds))
                if ($remainingBudget -le 0) { Write-Stage 'capital_path_unavailable: no preparation budget'; exit 2 }
                $fallbackArgs = @('-m','quant.execution.paper_order_fallback','--notify','--to',$requestedDate,'--budget-seconds',"$remainingBudget",'--output',($logFile+'.fallback'))
                if ($accountWriters.Count -gt 0) { $fallbackArgs += '--account-writer' }
                $fallbackCode = Invoke-Python $fallbackArgs -Append
                Write-Stage ('frozen_order_fallback_exit=' + $fallbackCode + '; full_daily_not_run')
                Notify-Failure 2
                exit $fallbackCode
            }
            $remaining = ($waitDeadline - (Get-Date)).TotalSeconds
            Start-Sleep -Milliseconds ([Math]::Max(1,[Math]::Min(5000,$remaining*1000)))
        }
        } while ($writers.Count -gt 0)
    }
    $runArgs = @('-m', 'quant', 'research', 'daily')
    if ($CheckOnly) { $runArgs += '--check-only' }
    if ($requestedDate) { $runArgs += @('--to', $requestedDate) }
    Write-Stage ('daily target=' + $requestedDate)
    $code = Invoke-Python $runArgs -Append
    # Reuse the evening task for the previous month's brief; its cache allows
    # only one paid narrative attempt and does not start monthly model training.
    if (-not $CheckOnly) {
        Write-Stage 'monthly_research_brief'
        $briefCode = Invoke-Python @('-m', 'quant', 'report', 'brief', '--scheduled', '--no-notify') -Append
        Write-Stage ('monthly_research_brief_exit=' + $briefCode)
        if ($code -eq 0 -and $briefCode -ne 0) { $code = 1 }
    }
    if ($code -ne 2) { Notify-Failure $code }
    # Full tests run independently at 00:30; diagnostics cannot hold paper orders.
    Write-Stage ('daily_exit=' + $code + ' doctor')
    Invoke-Python @('-m', 'quant', 'doctor', '--json', '--no-notify') -Append | Out-Null
    exit $code
} catch {
    $_.Exception.Message | Out-File $logFile -Append -Encoding utf8
    Notify-Failure 1
    exit 1
} finally {
    if ($pauseRequestId) {
        $null = & $python -m quant.core.capital_window release --request-id $pauseRequestId
    }
}
