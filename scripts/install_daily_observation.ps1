param([switch]$CheckOnlyTask)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$name = if ($CheckOnlyTask) { 'QuantitativeTrading-DailyObservation-Probe' } else { 'QuantitativeTrading-DailyObservation' }
$script = Join-Path $PSScriptRoot 'run_daily_observation.ps1'
$arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -File "' + $script + '"'
if ($CheckOnlyTask) { $arguments += ' -CheckOnly' }
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument $arguments -WorkingDirectory $workspace
$triggers = @(
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At ([datetime]::Today.AddHours(17).AddMinutes(30))
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At ([datetime]::Today.AddHours(21).AddMinutes(30))
)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 4) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$task = New-ScheduledTask -Action $action -Trigger $triggers -Settings $settings -Principal $principal -Description 'Run native Python daily observations and S0 ledger; no automated trading. Requires logged-in Windows user.'
# Refuse to replace an unrelated task with the same name.
$existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if ($existing -and (@($existing.Actions).Count -ne 1 -or $existing.Actions.Arguments -ne $arguments)) {
    throw "Existing task $name has different arguments; inspect before replacing."
}
Register-ScheduledTask -TaskName $name -InputObject $task -Force | Out-Null
$saved = Get-ScheduledTask -TaskName $name
[pscustomobject]@{Name=$saved.TaskName; State=[string]$saved.State; Execute=$saved.Actions.Execute;
    Arguments=$saved.Actions.Arguments; WorkingDirectory=$saved.Actions.WorkingDirectory;
    StartBoundary=@($saved.Triggers.StartBoundary); MultipleInstances=[string]$saved.Settings.MultipleInstances;
    User=$saved.Principal.UserId; LogonType=[string]$saved.Principal.LogonType} | ConvertTo-Json
