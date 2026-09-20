$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$script = Join-Path $PSScriptRoot 'run_minute_refresh.ps1'
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 12) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
foreach ($kind in @('Recent', 'History')) {
    $name = 'QuantitativeTrading-Minutes' + $kind
    $arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -File "' + $script + '"'
    if ($kind -eq 'History') { $arguments += ' -History' }
    $action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument $arguments -WorkingDirectory $workspace
    $times = if ($kind -eq 'Recent') { @('16:10', '21:10') } else { @('22:10') }
    $triggers = @($times | ForEach-Object { New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $_ })
    $existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($existing -and (@($existing.Actions).Count -ne 1 -or $existing.Actions.Arguments -ne $arguments)) { throw "Unexpected existing task: $name" }
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $triggers -Settings $settings -Principal $principal -Description 'Read-only mainland stock/ETF minute data capture; append-only raw, resumable, no trading.' -Force | Out-Null
    Get-ScheduledTask -TaskName $name | Select-Object TaskName,State
}
