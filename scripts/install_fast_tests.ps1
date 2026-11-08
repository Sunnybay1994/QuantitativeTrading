$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$name = 'QuantitativeTrading-FastTests'
$script = Join-Path $PSScriptRoot 'run_fast_tests.ps1'
$arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -File "'+$script+'"'
$existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if ($existing -and (@($existing.Actions).Count -ne 1 -or $existing.Actions.Arguments -ne $arguments)) {
    throw 'Unexpected FastTests action; preserve it for inspection'
}
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument $arguments -WorkingDirectory $workspace
$trigger = New-ScheduledTaskTrigger -Daily -At '00:30'
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Independent native fast tests; original 600-second gate, no daily-order dependency.' -Force | Out-Null
Get-ScheduledTask -TaskName $name | Select-Object TaskName,State
