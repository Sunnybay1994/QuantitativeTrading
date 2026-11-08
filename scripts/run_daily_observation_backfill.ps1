param([Parameter(Mandatory=$true)][string]$To, [ValidateRange(0,1440)][int]$MaxWaitMinutes=480)
$ErrorActionPreference = 'Stop'

function Get-BackfillCompletion([string]$Root, [string]$Target) {
    $records = @()
    $dailyRoot = Join-Path $Root 'artifacts/daily/sue_v2'
    if (Test-Path -LiteralPath $dailyRoot) {
        foreach ($directory in Get-ChildItem -LiteralPath $dailyRoot -Directory) {
            $summary = Join-Path $directory.FullName 'summary.json'
            if (-not (Test-Path -LiteralPath $summary)) { continue }
            try {
                $value = Get-Content -LiteralPath $summary -Raw -Encoding UTF8 | ConvertFrom-Json
                $execution = Join-Path $directory.FullName 'scheduler.json'
                if ((Test-Path -LiteralPath $execution) -and
                    (Get-Content -LiteralPath $execution -Raw -Encoding UTF8 | ConvertFrom-Json).exit_code -ne 0) { continue }
                if ($value.as_of -eq $Target -and $value.status -eq 'complete' -and
                    $value.rehearsal -eq $false -and $value.saved_data -eq $false) { $records += $summary }
            } catch { continue }
        }
    }
    $contextPath = Join-Path $Root 'artifacts/daily/market_context/latest.json'
    $context = $null
    if (Test-Path -LiteralPath $contextPath) {
        try { $context = Get-Content -LiteralPath $contextPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch { }
    }
    return @{daily_complete=($records.Count -gt 0); daily_records=@($records);
        market_context_complete=($null -ne $context -and $context.status -eq 'complete' -and $context.date -eq $Target);
        market_context_date=$context.date; market_context_path=$contextPath}
}

function Invoke-DailyBackfill([string]$Target, [int]$WaitMinutes) {
    $workspace = Split-Path -Parent $PSScriptRoot
    Set-Location -LiteralPath $workspace
    $day = [datetime]::ParseExact($Target, 'yyyy-MM-dd', [cultureinfo]::InvariantCulture)
    if ($day.Date -gt (Get-Date).Date) { throw 'Cannot backfill a future date' }
    $logRoot = Join-Path $workspace 'artifacts/daily/scheduler'
    New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
    $log = Join-Path $logRoot ('do_backfill_waiter_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fffffff') + '.log')
    $statusPath = Join-Path $logRoot 'do_backfill_status.json'
    $started = (Get-Date).ToString('o')
    function Log([string]$Message) { Add-Content -LiteralPath $log -Value ((Get-Date).ToString('o')+' '+$Message) -Encoding UTF8 }
    function Save-State([string]$Status, [hashtable]$Extra) {
        $state = @{status=$Status; to=$Target; started_at=$started; updated_at=(Get-Date).ToString('o');
            log=$log; pid=$PID; max_wait_minutes=$WaitMinutes; auto_trade=$false}
        foreach ($key in $Extra.Keys) { $state[$key] = $Extra[$key] }
        $temporary = $statusPath + '.' + $PID + '.tmp'
        $state | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temporary -Encoding UTF8
        Move-Item -LiteralPath $temporary -Destination $statusPath -Force
    }
    $pattern = 'quant research (daily|nightly|mining|cycle|gp)|quant data (refresh|minute-factors|baostock-history)|quant\.(data\.(refresh|refresh_minute_factors|intraday|baostock_history)|factors\.compute|research\.(continuous_mining|run_daily|scheduled_observation|run_factor_search|run_research_cycle|nightly|run_genetic_factor_search|run_constrained_portfolio|run_multifactor)|execution\.(stock_paper|q10_paper|paper_ledger|cross_asset_forward))'
    $deadline = (Get-Date).AddMinutes($WaitMinutes)
    try {
        Log ('waiter start To='+$Target+' MaxWaitMinutes='+$WaitMinutes)
        while ($true) {
            $writers = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
                Where-Object { $_.CommandLine -and $_.CommandLine -match $pattern })
            if ($writers.Count -eq 0) { break }
            $writerPids = @($writers.ProcessId)
            if ((Get-Date) -ge $deadline) {
                Log ('TIMEOUT blocked by '+($writerPids -join ','))
                Save-State 'do_backfill_timed_out' @{exit_code=3; writer_pids=$writerPids; reason='Writer wait deadline elapsed'}
                return 3
            }
            Save-State 'do_backfill_waiting_writer' @{writer_pids=$writerPids}
            Log ('still waiting writers pids='+($writerPids -join ','))
            Start-Sleep -Seconds 45
        }
        Log 'writers free; launching existing DailyObservation entry point'
        Save-State 'do_backfill_running' @{writer_pids=@()}
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'run_daily_observation.ps1') -To $Target -WaitForWriter
        $code = $LASTEXITCODE
        Log ('daily observation exit_code='+$code)
        $completion = Get-BackfillCompletion $workspace $Target
        $completion['exit_code'] = $code
        if ($code -eq 0 -and $completion.daily_complete -and $completion.market_context_complete) {
            Save-State 'do_backfill_finished' $completion
            return 0
        }
        if ($code -eq 0) { $code=1; $completion['exit_code']=$code }
        Save-State 'do_backfill_incomplete' $completion
        return $code
    } catch {
        Log ('ERROR '+$_.Exception.Message)
        Save-State 'do_backfill_failed' @{exit_code=1; error=$_.Exception.Message}
        return 1
    }
}

if ($MyInvocation.InvocationName -ne '.') { exit (Invoke-DailyBackfill $To $MaxWaitMinutes) }
