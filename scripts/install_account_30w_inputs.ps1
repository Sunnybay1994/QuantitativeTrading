param([switch]$Install)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$name = 'QuantitativeTrading-Account30wInputs'
$command = [System.Security.SecurityElement]::Escape("$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe")
$script = Join-Path $workspace 'scripts\run_account_30w_inputs.ps1'
$arguments = [System.Security.SecurityElement]::Escape('-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "'+$script+'"')
$directory = [System.Security.SecurityElement]::Escape($workspace)
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$payload = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
 <RegistrationInfo><Description>Prepare exact-session two-ETF inputs at 21:05; no account advance or orders.</Description></RegistrationInfo>
 <Triggers><CalendarTrigger><StartBoundary>2026-11-16T21:05:00+08:00</StartBoundary><Enabled>true</Enabled><ScheduleByWeek><DaysOfWeek><Monday/><Tuesday/><Wednesday/><Thursday/><Friday/></DaysOfWeek><WeeksInterval>1</WeeksInterval></ScheduleByWeek></CalendarTrigger></Triggers>
 <Principals><Principal id="Author"><UserId>$user</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
 <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><StartWhenAvailable>false</StartWhenAvailable><ExecutionTimeLimit>PT10M</ExecutionTimeLimit></Settings>
 <Actions Context="Author"><Exec><Command>$command</Command><Arguments>$arguments</Arguments><WorkingDirectory>$directory</WorkingDirectory></Exec></Actions>
</Task>
"@
$output = Join-Path $workspace 'artifacts\maintenance\review_20261115\account_inputs'
New-Item -ItemType Directory -Path $output -Force | Out-Null
$xml = Join-Path $output ($name+'.xml')
$payload | Set-Content -LiteralPath $xml -Encoding Unicode
if ($Install) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) { throw 'Task exists; inspect it before replacement' }
    Register-ScheduledTask -TaskName $name -Xml $payload | Out-Null
    $task = Get-ScheduledTask -TaskName $name
    $info = $task | Get-ScheduledTaskInfo
    [pscustomobject]@{Task=$name;State=[string]$task.State;NextRunTime=$info.NextRunTime.ToString('o');LastTaskResult=$info.LastTaskResult} | ConvertTo-Json
}
Write-Output $xml
