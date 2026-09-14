$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + (Join-Path $PSScriptRoot 'run_continuous_mining.ps1') + '"') -WorkingDirectory $workspace
$login = New-ScheduledTaskTrigger -AtLogOn -User $identity
$repeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 10)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 3) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$backup = Join-Path $workspace 'artifacts\maintenance\continuous_mining_deployment_20260914'
New-Item -ItemType Directory -Path $backup -Force | Out-Null
$old = Get-ScheduledTask -TaskName 'QuantitativeTrading-NightlyResearch' -ErrorAction SilentlyContinue
if ($old -and -not (Test-Path -LiteralPath (Join-Path $backup 'previous_nightly.xml'))) {
    Export-ScheduledTask -TaskName $old.TaskName | Set-Content -LiteralPath (Join-Path $backup 'previous_nightly.xml') -Encoding utf8
}
Register-ScheduledTask -TaskName 'QuantitativeTrading-ContinuousMining' -Action $action -Trigger @($login,$repeat) -Settings $settings -Principal $principal -Force | Out-Null
if ($old) { Disable-ScheduledTask -TaskName $old.TaskName | Out-Null }
Get-ScheduledTask -TaskName 'QuantitativeTrading-ContinuousMining' | Select-Object TaskName,State
