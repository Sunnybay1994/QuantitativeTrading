$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$name = 'QuantitativeTrading-RealtimeQuotes'
$script = Join-Path $PSScriptRoot 'run_realtime_quotes.ps1'
$arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -File "' + $script + '"'
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument $arguments -WorkingDirectory $workspace
$triggers = @(
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At ([datetime]::Today.AddHours(9).AddMinutes(20))
    New-ScheduledTaskTrigger -AtLogOn -User ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 7) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 2) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if ($existing -and (@($existing.Actions).Count -ne 1 -or $existing.Actions.Arguments -ne $arguments)) {
    throw "Existing task $name has different arguments; refusing replacement."
}
$task = New-ScheduledTask -Action $action -Trigger $triggers -Settings $settings -Principal $principal -Description 'Read-only mainland real-time quotes and minute feed. Requires logged-in Windows and Futu OpenD. No trading or historical K-line requests.'
Register-ScheduledTask -TaskName $name -InputObject $task -Force | Out-Null
$saved = Get-ScheduledTask -TaskName $name
[pscustomobject]@{Name=$saved.TaskName; State=[string]$saved.State; Arguments=$saved.Actions.Arguments;
    StartBoundary=@($saved.Triggers.StartBoundary); LogonType=[string]$saved.Principal.LogonType} | ConvertTo-Json
