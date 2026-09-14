param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $workspace
$env:PYTHONPATH = Join-Path $workspace 'src'
$env:POLARS_MAX_THREADS = '4'
$env:PYTHONUTF8 = '1'
$python = 'D:\Miniforge3\python.exe'
$logRoot = Join-Path $workspace 'artifacts\research\nightly\scheduler'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$logFile = Join-Path $logRoot ((Get-Date -Format 'yyyy-MM-dd_HHmmss_fffffff') + '.log')
try {
    # Reuse daily observation's process-based writer protection and IgnoreNew.
    $writers = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -match 'quant\.(data\.(refresh|intraday)|factors\.compute|research\.(nightly|run_daily|scheduled_observation|run_factor_search|run_genetic_factor_search|run_research_cycle|run_constrained|run_multifactor)|execution\.(q10_paper|stock_paper|paper_ledger|cross_asset_forward))' })
    if ($writers.Count -gt 0) {
        'Deferred: another data/factor/account writer is running.' | Out-File $logFile -Encoding utf8
        if (-not $CheckOnly) {
            & $python -m quant.research.nightly --config configs/research/nightly.toml --deferred-reason 'Another data/factor/account writer is running.' *>> $logFile
        }
        exit 2
    }
    if ($CheckOnly) {
        'Ready: no conflicting writer.' | Out-File $logFile -Encoding utf8
        exit 0
    }
    & $python -m quant.research.nightly --config configs/research/nightly.toml *> $logFile
    exit $LASTEXITCODE
} catch {
    $_.Exception.Message | Out-File $logFile -Append -Encoding utf8
    exit 1
}
