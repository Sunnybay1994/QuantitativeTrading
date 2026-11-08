param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $workspace
$env:PYTHONPATH = Join-Path $workspace 'src'
$env:POLARS_MAX_THREADS = '4'
$env:PYTHONUTF8 = '1'
$root = Join-Path $workspace 'artifacts\research\continuous'
if (-not $CheckOnly) { New-Item -ItemType Directory -Path $root -Force | Out-Null }
$clock = Get-Date
$hours = 2.0
$reason = $null
$python = 'D:\Miniforge3\python.exe'
$env:QUANT_BACKGROUND_WRITER = '1'
. (Join-Path $PSScriptRoot 'capital_path_window.ps1')
if (Test-CapitalPathPause) { $reason = 'Capital path window or pause request' }
# A dated, bounded data slot affects future launches only; active workers retain
# their checkpoints and finish normally. Expiry restores research automatically.
$reservationPath = Join-Path $root 'data_window.json'
if (Test-Path -LiteralPath $reservationPath) {
    $reservation = Get-Content -LiteralPath $reservationPath -Raw | ConvertFrom-Json
    $slotStart = [DateTimeOffset]::Parse($reservation.starts_at)
    $slotEnd = [DateTimeOffset]::Parse($reservation.expires_at)
    $slotClock = [DateTimeOffset]$clock
    if ($slotEnd -le $slotStart -or ($slotEnd - $slotStart).TotalHours -gt 4) {
        throw 'Data reservation must be positive and at most four hours'
    }
    if ($slotClock -ge $slotStart -and $slotClock -lt $slotEnd) {
        $slotStatus = @{status='deferred'; updated_at=$clock.ToString('o');
            reason='Reserved BaoStock data collection window'; reservation=$reservationPath;
            retry_after=$reservation.expires_at}
        if ($CheckOnly) { $slotStatus | ConvertTo-Json; exit 0 }
        $slotStatus | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root 'scheduler.json') -Encoding utf8
        exit 0
    }
    # Do not start a two-hour research slice across an upcoming reserved slot.
    if ($slotClock -lt $slotStart) {
        $hours = [Math]::Min($hours, ($slotStart - $slotClock).TotalHours)
    }
}
if ([int]$clock.DayOfWeek -in 1,2,3,4,5) {
    foreach ($hour in 17,21) {
        $cutoff = $clock.Date.AddHours($hour).AddMinutes(20)
        $end = $cutoff.AddMinutes(20)
        if ($clock -ge $cutoff -and $clock -lt $end) { $reason = 'Reserved for daily observation' }
        if ($clock -lt $cutoff) { $hours = [Math]::Min($hours, ($cutoff - $clock).TotalHours) }
    }
}
$writers = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -match 'quant research (daily|nightly|mining|cycle|gp)|quant data (refresh|minute-factors|minutes|minute-history|baostock-history)|quant\.(data\.(refresh|refresh_minute_factors|intraday|baostock_history|recent_minutes|minute_history)|factors\.compute|research\.(continuous_mining|nightly|run_daily|scheduled_observation|run_factor_search|run_genetic_factor_search|run_research_cycle|run_constrained|run_multifactor)|execution\.(q10_paper|stock_paper|paper_ledger|cross_asset_forward))|daily_recovery.+recover.py' })
if ($writers.Count -gt 0) { $reason = 'Another data/factor/account writer is running' }
if ($hours -lt (1.0 / 60)) { $reason = 'Daily observation starts shortly' }
if ($reason) {
    $deferred = @{status='deferred'; updated_at=$clock.ToString('o'); reason=$reason}
    if ($CheckOnly) { $deferred | ConvertTo-Json; exit 0 }
    $deferred |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root 'scheduler.json') -Encoding utf8
    exit 0
}
if ($CheckOnly) { Write-Output "Ready; maximum slice hours: $hours"; exit 0 }
$logRoot = Join-Path $root 'scheduler'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$log = Join-Path $logRoot ($clock.ToString('yyyy-MM-dd_HHmmss_fffffff') + '.log')
@{status='started'; updated_at=$clock.ToString('o'); log=$log; slice_hours=$hours} |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root 'scheduler.json') -Encoding utf8
$hoursText = $hours.ToString('0.######',[Globalization.CultureInfo]::InvariantCulture)
try {
    & $python -m quant research minutes *> ($log + '.minutes.log')
    $minuteCode = $LASTEXITCODE
    & $python -m quant.notify.automation_alert --task '分钟策略研究' --code $minuteCode --log ($log + '.minutes.log') *>> $log
    # Minute failure must not stop the factor queue.
    & $python -m quant research mining --config configs/research/nightly.toml --output-root artifacts/research/continuous --slice-hours $hoursText *>> $log
    $code = $LASTEXITCODE
    if ($code -ne 2) { & $python -m quant.notify.automation_alert --task '持续挖掘' --code $code --log $log *>> $log }
    exit $code
} catch {
    $_.Exception.Message | Out-File $log -Append -Encoding utf8
    & $python -m quant.notify.automation_alert --task '持续挖掘' --code 1 --log $log *>> $log
    exit 1
}
