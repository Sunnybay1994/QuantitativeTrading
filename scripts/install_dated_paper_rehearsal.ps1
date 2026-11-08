param([switch]$Install)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$name = 'QuantitativeTrading-DatedPaperRehearsal-20261127'
$script = Join-Path $PSScriptRoot 'run_dated_paper_rehearsal.ps1'
$command = [System.Security.SecurityElement]::Escape("$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe")
$arguments = [System.Security.SecurityElement]::Escape('-NoProfile -NonInteractive -WindowStyle Hidden -File "' + $script + '"')
$directory = [System.Security.SecurityElement]::Escape($workspace)
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
# Exporting a reviewable XML does not need Task Scheduler service access.
$payload = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>One-off isolated three-account rehearsal; no push or automatic retry.</Description></RegistrationInfo>
  <Triggers><TimeTrigger><StartBoundary>2026-11-27T22:00:00+08:00</StartBoundary><Enabled>true</Enabled></TimeTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>$user</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><StartWhenAvailable>false</StartWhenAvailable><ExecutionTimeLimit>PT2H</ExecutionTimeLimit></Settings>
  <Actions Context="Author"><Exec><Command>$command</Command><Arguments>$arguments</Arguments><WorkingDirectory>$directory</WorkingDirectory></Exec></Actions>
</Task>
"@
$folder = Join-Path $workspace 'artifacts\paper\dated_rehearsal'
New-Item -ItemType Directory -Path $folder -Force | Out-Null
$xml = Join-Path $folder ($name + '.xml')
$payload | Set-Content -LiteralPath $xml -Encoding Unicode
if ($Install) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) { throw 'Task exists; inspect and preserve existing XML' }
    Register-ScheduledTask -TaskName $name -Xml $payload | Out-Null
}
Write-Output $xml
