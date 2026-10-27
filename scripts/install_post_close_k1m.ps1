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
        [Parameter(Mandatory)][string]$Description,
        [Parameter(Mandatory)][DayOfWeek[]]$Days
    )
    $action = New-ScheduledTaskAction -Execute $psExe -Argument $Arguments -WorkingDirectory $workspace
    $triggers = @(
        New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Days -At $At
    )
    $existing = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
    if ($existing -and (@($existing.Actions).Count -ne 1 -or $existing.Actions.Arguments -ne $Arguments)) {
        Unregister-ScheduledTask -TaskName $Name -Confirm:$false
    }
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $triggers -Settings $settings -Principal $principal -Description $Description -Force | Out-Null
    Get-ScheduledTask -TaskName $Name | Select-Object TaskName, State | Format-List
}

$weekdays = @([DayOfWeek]::Monday, [DayOfWeek]::Tuesday, [DayOfWeek]::Wednesday, [DayOfWeek]::Thursday, [DayOfWeek]::Friday)
# Friday's US cash session is ready after 05:00 Saturday, Shanghai time. 06:00 covers both EST and EDT.
$usDays = @([DayOfWeek]::Tuesday, [DayOfWeek]::Wednesday, [DayOfWeek]::Thursday, [DayOfWeek]::Friday, [DayOfWeek]::Saturday)

$cnArgs = '-NoProfile -NonInteractive -WindowStyle Hidden -File "' + $script + '" -Markets cn'
Register-PostCloseK1MTask -Name 'QuantitativeTrading-PostCloseK1M' -Arguments $cnArgs `
    -At ([datetime]::Today.AddHours(15).AddMinutes(10)) -Days $weekdays `
    -Description 'Post-close A-share 1m at 15:10 via Futu K_1M. No trading.'

$hkArgs = '-NoProfile -NonInteractive -WindowStyle Hidden -File "' + $script + '" -Markets hk -MaxSeconds 3600'
Register-PostCloseK1MTask -Name 'QuantitativeTrading-PostCloseK1M-HK' -Arguments $hkArgs `
    -At ([datetime]::Today.AddHours(16).AddMinutes(40)) -Days $weekdays `
    -Description 'Post-close HK 1m at 16:40 via Futu K_1M. No trading.'

$usArgs = '-NoProfile -NonInteractive -WindowStyle Hidden -File "' + $script + '" -Markets us -MaxSeconds 1800'
Register-PostCloseK1MTask -Name 'QuantitativeTrading-PostCloseK1M-US' -Arguments $usArgs `
    -At ([datetime]::Today.AddHours(6)) -Days $usDays `
    -Description 'US 1m at 06:00 Shanghai, after the previous US cash close in both EST and EDT. No trading.'

$combined = Get-ScheduledTask -TaskName 'QuantitativeTrading-PostCloseK1M-HKUS' -ErrorAction SilentlyContinue
if ($combined) {
    Unregister-ScheduledTask -TaskName 'QuantitativeTrading-PostCloseK1M-HKUS' -Confirm:$false
}
