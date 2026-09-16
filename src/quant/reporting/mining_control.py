"""Resume the existing Windows task, retaining its writer and daily guards."""
import json
import secrets
import subprocess


def authorized(headers, token: str, port: int) -> bool:
    hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
    return (headers.get('Host') in hosts
            and headers.get('Origin') in {f'http://{h}' for h in hosts}
            and headers.get('Content-Length', '0') == '0'
            and not headers.get('Transfer-Encoding')
            and secrets.compare_digest(headers.get('X-Mining-Token', ''), token))


def resume() -> dict:
    script = r'''$ErrorActionPreference = 'Stop'
$task = Get-ScheduledTask -TaskName 'QuantitativeTrading-ContinuousMining'
if ($task.Settings.MultipleInstances -ne 'IgnoreNew') { throw 'Task must use IgnoreNew instance policy' }
if ($task.State -eq 'Disabled') { throw 'Mining task is disabled; inspect task configuration' }
$active = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -match 'quant research (mining|nightly)|quant\.research\.(continuous_mining|nightly)' })
if ($active.Count -gt 0 -or $task.State -eq 'Running') {
    @{state='already_running'; message='投研任务已在运行或启动中，未重复启动'; pids=@($active.ProcessId)} | ConvertTo-Json -Compress
} else {
    Start-ScheduledTask -TaskName 'QuantitativeTrading-ContinuousMining'
    @{state='requested'; message='已请求从断点恢复；启动器仍检查日更避让与写入互斥，请查看实际进程状态'} | ConvertTo-Json -Compress
}'''
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                             '[Console]::OutputEncoding = [System.Text.Encoding]::UTF8;\n'+script],
                            capture_output=True, encoding='utf-8', timeout=20, check=True)
    return json.loads(result.stdout.lstrip('\ufeff'))
