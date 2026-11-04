$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$script = Join-Path $PSScriptRoot 'run_paper_insurance.ps1'
$plans = @(
    @{Name='QuantitativeTrading-PaperOrderWatch'; Mode='Watch'; Trigger=(New-ScheduledTaskTrigger -Daily -At '22:30')},
    @{Name='QuantitativeTrading-PaperRehearsal'; Mode='Rehearse'; Trigger=(New-ScheduledTaskTrigger -Once -At ([datetime]'2026-11-27T22:10:00'))}
)
$backup = Join-Path $workspace ('artifacts\maintenance\paper_insurance_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach ($plan in $plans) {
    $old = Get-ScheduledTask -TaskName $plan.Name -ErrorAction SilentlyContinue
    if ($old) {
        Export-ScheduledTask -TaskName $plan.Name | Set-Content -LiteralPath (Join-Path $backup ($plan.Name + '.xml')) -Encoding utf8
    }
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -WorkingDirectory $workspace -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $script + '" -Mode ' + $plan.Mode)
    Register-ScheduledTask -TaskName $plan.Name -Action $action -Trigger $plan.Trigger -Settings $settings -Principal $principal -Force | Out-Null
    $task = Get-ScheduledTask -TaskName $plan.Name
    $info = Get-ScheduledTaskInfo -TaskName $plan.Name
    [pscustomobject]@{Name=$task.TaskName; State=[string]$task.State; NextRun=$info.NextRunTime.ToString('o'); LastResult=$info.LastTaskResult}
}
