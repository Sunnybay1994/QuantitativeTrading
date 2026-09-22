param([switch]$Probe)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $workspace
$env:PYTHONPATH = Join-Path $workspace 'src'
$env:POLARS_MAX_THREADS = '2'
$env:PYTHONUTF8 = '1'
$logRoot = Join-Path $workspace 'artifacts/realtime/futu/scheduler'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$logFile = Join-Path $logRoot ((Get-Date -Format 'yyyy-MM-dd_HHmmss_fffffff') + '.log')
$action = if ($Probe) { 'probe' } else { 'run' }
$python = 'D:\Miniforge3\python.exe'
try {
    & $python -m quant data realtime $action *> $logFile
    $code = $LASTEXITCODE
    & $python -m quant.notify.automation_alert --task '实时行情采集' --code $code --log $logFile *>> $logFile
    exit $code
} catch {
    $_.Exception.Message | Out-File $logFile -Append -Encoding utf8
    & $python -m quant.notify.automation_alert --task '实时行情采集' --code 1 --log $logFile *>> $logFile
    exit 1
}
