param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $workspace
$env:PYTHONPATH = Join-Path $workspace 'src'
$env:POLARS_MAX_THREADS = '4'
$env:PYTHONUTF8 = '1'
$python = 'D:\Miniforge3\python.exe'
$logRoot = Join-Path $workspace 'artifacts\daily\scheduler'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$logFile = Join-Path $logRoot ((Get-Date -Format 'yyyy-MM-dd_HHmmss_fffffff') + '.log')
try {
    if (-not $CheckOnly) {
        # Task Scheduler IgnoreNew handles its own overlap. Also defer to ad-hoc writers.
        $writers = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
            Where-Object { $_.CommandLine -match 'quant\.(data\.(refresh|intraday)|factors\.compute|research\.(run_daily|run_factor_search)|execution\.(stock_paper|paper_ledger|cross_asset_forward))' })
        if ($writers.Count -gt 0) {
            'Deferred: another data/factor/account writer is running.' | Out-File $logFile -Encoding utf8
            exit 2
        }
    }
    $runArgs = @('-m', 'quant.research.scheduled_observation')
    if ($CheckOnly) { $runArgs += '--check-only' }
    & $python @runArgs *> $logFile
    exit $LASTEXITCODE
} catch {
    $_.Exception.Message | Out-File $logFile -Append -Encoding utf8
    exit 1
}
