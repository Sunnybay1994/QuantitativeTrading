$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$name = 'QuantitativeTrading-BaostockHistory'
$script = Join-Path $PSScriptRoot 'run_baostock_history.ps1'
$arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -File "' + $script + '"'
$existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if ($existing -and (@($existing.Actions).Count -ne 1 -or $existing.Actions.Arguments -ne $arguments)) { throw 'Unexpected existing task' }
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument $arguments -WorkingDirectory $workspace
$triggers = @(0..23 | ForEach-Object { New-ScheduledTaskTrigger -Daily -At ('{0:00}:25' -f $_) })
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $name -Action $action -Trigger $triggers -Settings $settings -Principal $principal -Description 'Full-market BaoStock history and daily accumulation, resumable yearly checkpoints, no trading.' -Force | Out-Null
