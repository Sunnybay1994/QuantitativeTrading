param([switch]$CheckOnly, [ValidateRange(1024,65535)][int]$Port = 8769)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $workspace
$mutex = New-Object System.Threading.Mutex($false, 'Local\QuantitativeTrading-ResearchDashboard')
$owned = $false
function Test-PortOpen([int]$TargetPort) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $client.Connect('127.0.0.1', $TargetPort)
        return $true
    } catch [System.Net.Sockets.SocketException] {
        return $false
    } finally {
        $client.Dispose()
    }
}
try {
    try { $owned = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $owned = $true }
    if (-not $owned) { Write-Output 'Dashboard launcher already owns the instance'; exit 0 }
    if (Test-PortOpen $Port) {
        Write-Output "Port $Port is already occupied; no duplicate dashboard was started"
        exit 0
    }
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
        if (Test-PortOpen $Port) {
            Write-Output "Port $Port became occupied before launch; treating as ready"
            exit 0
        }
        $log = Join-Path $logs ((Get-Date).ToString('yyyyMMdd_HHmmss_fffffff') + '.log')
        # Detach: Task Scheduler must finish with result=0 while the HTTP service keeps running.
        $service = Start-Process -FilePath 'D:\Miniforge3\python.exe' -ArgumentList '-m','quant.reporting.research_dashboard','--port',([string]$Port) -WorkingDirectory $workspace -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError ($log+'.stderr') -PassThru
        $ready = $false
        for ($tick = 0; $tick -lt 45; $tick++) {
            if (Test-PortOpen $Port) { $ready = $true; break }
            if ($service.HasExited) { break }
            Start-Sleep -Seconds 1
        }
        if ($ready) {
            Write-Output "Dashboard listening on port $Port pid=$($service.Id)"
            exit 0
        }
        if (-not $service.HasExited) {
            Stop-Process -Id $service.Id -Force -ErrorAction SilentlyContinue
        }
        if ($attempt -eq 3) { exit 1 }
        Start-Sleep -Seconds 5
    }
} finally {
    if ($owned) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
