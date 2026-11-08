# Shared by existing launchers. This does not start, stop or suspend a worker.
function Test-CapitalPathPause {
    $clock = Get-Date
    $request = Join-Path $workspace 'artifacts/runtime/capital_path_pause.json'
    # Preserve read-only launcher probes outside the relevant clock range.
    if (-not (Test-Path -LiteralPath $request) -and
        ($clock.TimeOfDay -lt [timespan]'20:30' -or $clock.TimeOfDay -ge [timespan]'23:30')) { return $false }
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $null = & $python -m quant.core.capital_window check 2>&1
        if ($LASTEXITCODE -eq 75) { return $true }
        if ($LASTEXITCODE -ne 0) { throw 'Capital-path calendar/request check failed' }
        return $false
    } finally { $ErrorActionPreference = $previous }
}
