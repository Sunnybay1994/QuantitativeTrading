$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $workspace
$env:PYTHONPATH = Join-Path $workspace 'src'
$env:PYTHONUTF8 = '1'
$env:POLARS_MAX_THREADS = '4'
$python = 'D:\Miniforge3\python.exe'
foreach ($candidate in @('C:\Program Files\Git\cmd','C:\Program Files\Git\bin','D:\Miniforge3\Library\bin')) {
    if (Test-Path -LiteralPath (Join-Path $candidate 'git.exe')) { $env:Path=$candidate+';'+$env:Path; break }
}
$logs = Join-Path $workspace 'artifacts/tests/scheduler'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$log = Join-Path $logs ((Get-Date -Format 'yyyyMMdd_HHmmss_fffffff')+'.log')
$ErrorActionPreference = 'Continue'
& $python -m quant doctor --record-tests *> $log
$code = $LASTEXITCODE
& $python -m quant doctor --json --no-notify *>> $log
& $python -m quant.notify.automation_alert --task 'FastTests' --code $code --log $log *>> $log
exit $code
