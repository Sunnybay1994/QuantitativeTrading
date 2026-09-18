$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$name = 'QuantitativeTrading-ResearchDashboard'
$launcher = Join-Path $PSScriptRoot 'run_research_dashboard.ps1'
$old = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if ($old) {
    if ($old.Actions.Arguments -notlike "*$launcher*") { throw 'Existing task has a different launcher; retain it' }
    $backup = Join-Path $workspace 'artifacts\maintenance\dashboard_service'
    New-Item -ItemType Directory -Path $backup -Force | Out-Null
    Export-ScheduledTask -TaskName $name | Set-Content -LiteralPath (Join-Path $backup ((Get-Date).ToString('yyyyMMdd_HHmmss_fffffff')+'.xml')) -Encoding utf8
}
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "'+$launcher+'"') -WorkingDirectory $workspace
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Get-ScheduledTask -TaskName $name | Select-Object TaskName,State
