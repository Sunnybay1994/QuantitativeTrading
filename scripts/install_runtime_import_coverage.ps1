param([switch]$Install)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$name = 'QuantitativeTrading-RuntimeImportCoverage-20261123'
$launcher = Join-Path $PSScriptRoot 'run_runtime_import_coverage.ps1'
$command = [System.Security.SecurityElement]::Escape("$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe")
$arguments = [System.Security.SecurityElement]::Escape('-NoProfile -NonInteractive -WindowStyle Hidden -File "' + $launcher + '"')
$directory = [System.Security.SecurityElement]::Escape($workspace)
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$payload = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>One-off H1 import observation report; never moves source files.</Description></RegistrationInfo>
  <Triggers><TimeTrigger><StartBoundary>2026-11-23T10:05:00+08:00</StartBoundary><Enabled>true</Enabled></TimeTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>$user</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><StartWhenAvailable>true</StartWhenAvailable><ExecutionTimeLimit>PT10M</ExecutionTimeLimit></Settings>
  <Actions Context="Author"><Exec><Command>$command</Command><Arguments>$arguments</Arguments><WorkingDirectory>$directory</WorkingDirectory></Exec></Actions>
</Task>
"@
$folder = Join-Path $workspace 'artifacts\maintenance\h1_coverage_20261109'
New-Item -ItemType Directory -Path $folder -Force | Out-Null
$xml = Join-Path $folder 'scheduled_task.template.xml'
$payload | Set-Content -LiteralPath $xml -Encoding Unicode
if ($Install) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
        Export-ScheduledTask -TaskName $name |
            Set-Content -LiteralPath (Join-Path $folder 'existing_task.xml') -Encoding Unicode
        throw 'Task exists; preserved its XML for inspection without replacement.'
    }
    Register-ScheduledTask -TaskName $name -Xml $payload | Out-Null
}
Write-Output $xml
