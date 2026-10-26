param([switch]$DryRun)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $workspace
$env:PYTHONPATH = Join-Path $workspace 'src'
$env:PYTHONUTF8 = '1'
$python = 'D:\Miniforge3\python.exe'
$logRoot = Join-Path $workspace 'artifacts\intel\scheduler'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$logFile = Join-Path $logRoot ((Get-Date -Format 'yyyy-MM-dd_HHmmss') + '.log')
$argsList = @('-m', 'quant', 'intel', 'scan', '--config', 'configs/research/intel.toml')
if ($DryRun) { $argsList += '--dry-run' }
& $python @argsList *>> $logFile
$code = $LASTEXITCODE
if ($code -ne 0) {
    & $python -m quant.notify.automation_alert --task intel_weekly --code $code --log $logFile *>> $logFile
}
exit $code
