$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$script = Join-Path $PSScriptRoot 'run_post_close_k1m.ps1'
$psExe = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 3) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited

function Register-PostCloseK1MTask {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Arguments,
        [Parameter(Mandatory)][datetime]$At,
        [Parameter(Mandatory)][string]$Description
    )
    $action = New-ScheduledTaskAction -Execute $psExe -Argument $Arguments -WorkingDirectory $workspace
    $triggers = @(
        New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $At
    )
    $existing = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
    if ($existing -and (@($existing.Actions).Count -ne 1 -or $existing.Actions.Arguments -ne $Arguments)) {
        throw "Existing task $Name has different arguments; refusing replacement."
    }
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $triggers -Settings $settings -Principal $principal -Description $Description -Force | Out-Null
    Get-ScheduledTask -TaskName $Name | Select-Object TaskName, State | Format-List
}

# CN whole-market post-close K_1M at 15:10
$cnArgs = '-NoProfile -NonInteractive -WindowStyle Hidden -File "' + $script + '"'
Register-PostCloseK1MTask -Name 'QuantitativeTrading-PostCloseK1M' -Arguments $cnArgs `
    -At ([datetime]::Today.AddHours(15).AddMinutes(10)) `
    -Description 'Post-close whole-market 1m via Futu realtime K_1M subscribe (not History KL). Distinct from live RealtimeQuotes. No trading.'

# HK+US post-close K_1M at 17:00 (markets still open / post HK close window)
$hkusArgs = '-NoProfile -ExecutionPolicy Bypass -File "' + $script + '" -Markets hk,us -MaxSeconds 7200'
Register-PostCloseK1MTask -Name 'QuantitativeTrading-PostCloseK1M-HKUS' -Arguments $hkusArgs `
    -At ([datetime]::Today.AddHours(17)) `
    -Description 'Post-close HK+US 1m via Futu realtime K_1M subscribe (-Markets hk,us). Distinct from live RealtimeQuotes. No trading.'
