param([switch]$CheckOnly, [ValidateRange(1024,65535)][int]$Port = 8769)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $workspace
$mutex = New-Object System.Threading.Mutex($false, 'Local\QuantitativeTrading-ResearchDashboard')
$owned = $false
try {
    try { $owned = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $owned = $true }
    if (-not $owned) { Write-Output 'Dashboard launcher already owns the instance'; exit 0 }
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $client.Connect('127.0.0.1', $Port)
        Write-Output "Port $Port is already occupied; no duplicate dashboard was started"
        exit 0
    } catch [System.Net.Sockets.SocketException] {
        # No listener: the bound local server below remains the final single-instance guard.
    } finally { $client.Dispose() }
    if ($CheckOnly) {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
        try {
            $listener.Start()
            Write-Output "Ready to start local dashboard on port $Port"
        } finally { $listener.Stop() }
        exit 0
    }
    $env:PYTHONPATH = Join-Path $workspace 'src'
    $env:PYTHONUTF8 = '1'
    $env:POLARS_MAX_THREADS = '4'
    $logs = Join-Path $workspace 'artifacts\research\dashboard_service'
    New-Item -ItemType Directory -Path $logs -Force | Out-Null
    for ($attempt = 0; $attempt -le 3; $attempt++) {
        $log = Join-Path $logs ((Get-Date).ToString('yyyyMMdd_HHmmss_fffffff') + '.log')
        $service = Start-Process -FilePath 'D:\Miniforge3\python.exe' -ArgumentList '-m','quant.reporting.research_dashboard','--port',([string]$Port) -WorkingDirectory $workspace -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError ($log+'.stderr') -PassThru -Wait
        if ($null -ne $service.ExitCode -and $service.ExitCode -eq 0) { exit 0 }
        if ($attempt -eq 3) { exit 1 }
        # Bound retries in the launcher itself; Task Scheduler must not multiply them.
        Start-Sleep -Seconds 60
    }
} finally {
    if ($owned) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
