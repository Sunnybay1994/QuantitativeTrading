$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $PSScriptRoot 'run_nightly_research.ps1'
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $scriptPath + '"') -WorkingDirectory $workspace
$weekday = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At '22:30'
$saturday = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday -At '09:00'
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 21) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName 'QuantitativeTrading-NightlyResearch' -Action $action -Trigger @($weekday,$saturday) -Settings $settings -Principal $principal -Force | Out-Null
$registered = Get-ScheduledTask -TaskName 'QuantitativeTrading-NightlyResearch'
[pscustomobject]@{
    TaskName = $registered.TaskName
    State = [string]$registered.State
    UserId = $registered.Principal.UserId
    LogonType = [string]$registered.Principal.LogonType
    Actions = @($registered.Actions | ForEach-Object { [pscustomobject]@{Execute=$_.Execute; Arguments=$_.Arguments; WorkingDirectory=$_.WorkingDirectory} })
    Triggers = @($registered.Triggers | ForEach-Object { [pscustomobject]@{StartBoundary=$_.StartBoundary; DaysOfWeek=$_.DaysOfWeek; Enabled=$_.Enabled} })
} | ConvertTo-Json -Depth 4
