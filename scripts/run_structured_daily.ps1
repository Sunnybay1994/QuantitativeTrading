param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $workspace
$env:PYTHONPATH = Join-Path $workspace 'src'
$env:POLARS_MAX_THREADS = '4'
$env:PYTHONUTF8 = '1'
$env:QUANT_BACKGROUND_WRITER = '0'
# Scheduled tasks often lack the diagnostic tool PATH.
$gitCandidates = @(
    'D:\Miniforge3\Library\mingw64\bin',
    'D:\Miniforge3\Library\bin',
    'C:\Program Files\Git\cmd',
    'C:\Program Files\Git\bin'
)
foreach ($g in $gitCandidates) {
    if ((Test-Path -LiteralPath (Join-Path $g 'git.exe')) -and ($env:Path -notlike ("*$g*"))) {
        $env:Path = "$g;" + $env:Path
        break
    }
}
$python = 'D:\Miniforge3\python.exe'
$logRoot = Join-Path $workspace 'artifacts\data\structured_incremental\scheduler'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$stamp = Get-Date -Format 'yyyy-MM-dd_HHmmss_fffffff'
$logFile = Join-Path $logRoot ($stamp + '.log')
function Write-Stage([string]$stage) {
    ((Get-Date).ToString('o') + ' ' + $stage) | Out-File $logFile -Append -Encoding utf8
}
function Invoke-Python([string[]]$ArgumentList, [switch]$Append) {
    # Native stderr must not become a terminating error. Otherwise the first
    # traceback line aborts the script and the scheduled task loses the rest.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $python @ArgumentList 2>&1 | Out-File -FilePath $logFile -Encoding utf8 -Append:$Append
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
}
try {
    if (-not (Test-Path -LiteralPath $python)) {
        Write-Stage 'missing_python'
        exit 1
    }
    if ($CheckOnly) {
        # Probe only: import path, no Tushare / incremental refresh.
        Write-Stage 'check_only'
        $code = Invoke-Python @('-c', 'from quant.data import structured_incremental') -Append
        Write-Stage ('check_only_exit=' + $code)
        exit $code
    }
    $output = Join-Path $workspace ('artifacts\data\structured_incremental\' + $stamp)
    $asOf = Get-Date -Format 'yyyy-MM-dd'
    Write-Stage ('structured_incremental output=' + $output)
    $code = Invoke-Python @('-m', 'quant', 'data', 'structured-incremental', '--with-futures', '--as-of', $asOf, '--output', $output) -Append
    Write-Stage ('structured_daily_exit=' + $code)
    exit $code
} catch {
    $_.Exception.Message | Out-File $logFile -Append -Encoding utf8
    exit 1
}
