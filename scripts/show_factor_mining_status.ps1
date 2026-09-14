$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$root = Join-Path $workspace 'artifacts\research\continuous'
$task = Get-ScheduledTask -TaskName 'QuantitativeTrading-ContinuousMining' -ErrorAction SilentlyContinue
if ($task) {
    $info = $task | Get-ScheduledTaskInfo
    [pscustomobject]@{Task=$task.TaskName;State=[string]$task.State;Last=$info.LastRunTime;Next=$info.NextRunTime;ExitCode=$info.LastTaskResult} | Format-List
}
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -match 'quant\.research\.(continuous_mining|nightly)' } |
    Select-Object ProcessId,CreationDate,CommandLine | Format-List
foreach ($name in 'status.json','scheduler.json') {
    $path = Join-Path $root $name
    if (Test-Path -LiteralPath $path) {
        $record = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
        $record | Select-Object state,status,batch,run,updated_at,retry_after,reason,log | Format-List
        if ($record.run) {
            $run = Join-Path $workspace $record.run
            foreach ($step in 'N1','N2','N3','N4','N5') {
                [pscustomobject]@{Step=$step;Completed=(Test-Path -LiteralPath (Join-Path $run "$step\result.json"))} | Format-Table -HideTableHeaders
            }
            $progress = Join-Path $run 'N2\search_progress.json'
            if (Test-Path -LiteralPath $progress) { Get-Content -LiteralPath $progress -Raw -Encoding UTF8 }
        }
    }
}
