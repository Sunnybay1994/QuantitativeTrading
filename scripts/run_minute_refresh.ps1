param([switch]$History)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $workspace
$env:PYTHONPATH = Join-Path $workspace 'src'
$env:POLARS_MAX_THREADS = '2'
$env:PYTHONUTF8 = '1'
$kind = if ($History) { 'minute-history' } else { 'minutes' }
$logRoot = Join-Path $workspace 'artifacts\minute_refresh\scheduler'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$logFile = Join-Path $logRoot ($kind + '_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fffffff') + '.log')
$python = 'D:\Miniforge3\python.exe'
try {
    & $python -m quant data $kind *> $logFile
    $dataCode = $LASTEXITCODE
    & $python -m quant.notify.automation_alert --task $kind --code $dataCode --log $logFile *>> $logFile
    & $python -m quant research minutes *>> $logFile
    $researchCode = $LASTEXITCODE
    & $python -m quant.notify.automation_alert --task '分钟策略研究' --code $researchCode --log $logFile *>> $logFile
    if ($dataCode -ne 0) { exit $dataCode }
    exit $researchCode
} catch {
    $_.Exception.Message | Out-File $logFile -Append -Encoding utf8
    & $python -m quant.notify.automation_alert --task $kind --code 1 --log $logFile *>> $logFile
    exit 1
}
