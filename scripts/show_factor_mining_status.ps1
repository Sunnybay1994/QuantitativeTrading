$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$root = Join-Path $workspace 'artifacts\research\continuous'
$task = Get-ScheduledTask -TaskName 'QuantitativeTrading-ContinuousMining' -ErrorAction SilentlyContinue
if ($task) {
    $info = $task | Get-ScheduledTaskInfo
    [pscustomobject]@{Task=$task.TaskName;State=[string]$task.State;Last=$info.LastRunTime;Next=$info.NextRunTime;TaskSchedulerLastResult=$info.LastTaskResult} | Format-List
}
$processes = @()
try {
    $processes = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -match 'quant\.research\.(continuous_mining|nightly)' })
    $processes | Select-Object ProcessId,CreationDate,CommandLine | Format-List
    Write-Output "Live mining processes: $($processes.Count). Saved state below may describe an earlier attempt."
} catch {
    Write-Output "Process inspection unavailable: $($_.Exception.Message). Saved files cannot prove a worker is running."
}
foreach ($name in 'status.json','scheduler.json') {
    $path = Join-Path $root $name
    if (Test-Path -LiteralPath $path) {
        $record = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
        $record | Select-Object state,status,batch,run,updated_at,retry_after,reason,log | Format-List
        if ($record.run) {
            $run = Join-Path $workspace $record.run
            $rows = @()
            foreach ($step in 'N1','N2','N3','N4','N5') {
                $resultPath = Join-Path $run "$step\result.json"
                $workers = @($processes | Where-Object {
                    $_.CommandLine -match "--worker\s+$step(?:\s|$)" -and
                    $_.CommandLine.Replace('\','/').IndexOf($record.run.Replace('\','/'), [StringComparison]::OrdinalIgnoreCase) -ge 0
                })
                $state = 'No saved result'
                $reason = $null
                if (Test-Path -LiteralPath $resultPath) {
                    $saved = Get-Content -LiteralPath $resultPath -Raw -Encoding UTF8 | ConvertFrom-Json
                    $state = 'Saved result (not proof of current completion)'
                    $reason = $saved.reason
                    if ($saved.skipped -or $reason) { $state = 'Saved skip / diagnostic' }
                }
                if ($workers.Count -gt 0) { $state = 'Running worker' }
                $rows += [pscustomobject]@{Step=$step;Status=$state;PID=($workers.ProcessId -join ',');Reason=$reason}
            }
            $rows | Format-Table -AutoSize -Wrap
            $admissionPath = Join-Path $run 'N4\admission_progress.json'
            if (Test-Path -LiteralPath $admissionPath) {
                $admission = Get-Content -LiteralPath $admissionPath -Raw -Encoding UTF8 | ConvertFrom-Json
                [pscustomobject]@{
                    Stage = 'N4 saved checkpoint (not proof of a live worker)'
                    CompletedCandidates = @($admission.rows).Count
                    TotalCandidates = @($admission.candidates).Count
                    SavedAt = (Get-Item -LiteralPath $admissionPath).LastWriteTime
                } | Format-List
            }
            $progress = Join-Path $run 'N2\search_progress.json'
            if (Test-Path -LiteralPath $progress) {
                Write-Output "GP checkpoint progress (saved at $((Get-Item -LiteralPath $progress).LastWriteTime))"
                Get-Content -LiteralPath $progress -Raw -Encoding UTF8
            }
        }
    }
}
