param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$name = 'QuantitativeTrading-StructuredDaily'
$script = Join-Path $PSScriptRoot 'run_structured_daily.ps1'
$arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -File "' + $script + '"'
if ($CheckOnly) {
    [pscustomobject]@{Name=$name; Arguments=$arguments; WorkingDirectory=$workspace;
        Time='19:00'; Days='Monday-Friday'; MultipleInstances='IgnoreNew'; ExecutionTimeLimit='PT1H'} | ConvertTo-Json
    return
}
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument $arguments -WorkingDirectory $workspace
$triggers = @(
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At ([datetime]::Today.AddHours(19))
)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$task = New-ScheduledTask -Action $action -Trigger $triggers -Settings $settings -Principal $principal -Description 'Run structured data incremental refresh; no automated trading. Requires logged-in Windows user.'
$existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if ($existing) {
    $backup = Join-Path $workspace ('artifacts\maintenance\d2_tasks\' + (Get-Date -Format 'yyyyMMddTHHmmss_fffffff'))
    New-Item -ItemType Directory -Path $backup -Force | Out-Null
    Export-ScheduledTask -TaskName $name | Set-Content -LiteralPath (Join-Path $backup 'before.xml') -Encoding UTF8
}
Register-ScheduledTask -TaskName $name -InputObject $task -Force | Out-Null
$saved = Get-ScheduledTask -TaskName $name
[pscustomobject]@{Name=$saved.TaskName; State=[string]$saved.State; Execute=$saved.Actions.Execute;
    Arguments=$saved.Actions.Arguments; WorkingDirectory=$saved.Actions.WorkingDirectory;
    StartBoundary=@($saved.Triggers.StartBoundary); MultipleInstances=[string]$saved.Settings.MultipleInstances;
    User=$saved.Principal.UserId; LogonType=[string]$saved.Principal.LogonType} | ConvertTo-Json
