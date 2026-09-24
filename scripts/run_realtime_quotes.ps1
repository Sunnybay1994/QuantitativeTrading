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
    if (-not $Probe) {
        Start-Process -FilePath $python -ArgumentList @('-m','quant','paper','b16-forward') -WorkingDirectory $workspace -WindowStyle Hidden -RedirectStandardOutput ($logFile + '.b16.out') -RedirectStandardError ($logFile + '.b16.err') | Out-Null
        # Companion is read-only, bounded, and single-instance; core holdings feed stays independent.
        Start-Process -FilePath $python -ArgumentList @('-m','quant.data.market_snapshot','--session','--output','artifacts/realtime/market_snapshots') -WorkingDirectory $workspace -WindowStyle Hidden -RedirectStandardOutput ($logFile + '.market.out') -RedirectStandardError ($logFile + '.market.err') | Out-Null
    }
    & $python -m quant data realtime $action *> $logFile
    $code = $LASTEXITCODE
    & $python -m quant.notify.automation_alert --task '实时行情采集' --code $code --log $logFile *>> $logFile
    exit $code
} catch {
    $_.Exception.Message | Out-File $logFile -Append -Encoding utf8
    & $python -m quant.notify.automation_alert --task '实时行情采集' --code 1 --log $logFile *>> $logFile
    exit 1
}
