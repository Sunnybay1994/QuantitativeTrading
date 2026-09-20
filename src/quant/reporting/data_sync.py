"""Manually trigger only existing, guarded data collection tasks."""
import json
import subprocess
import threading

TASKS = {'recent': 'QuantitativeTrading-MinutesRecent', 'history': 'QuantitativeTrading-MinutesHistory',
         'daily': 'QuantitativeTrading-DailyObservation', 'realtime': 'QuantitativeTrading-RealtimeQuotes'}
_lock = threading.Lock()


def powershell(script):
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
        '[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; $ErrorActionPreference="Stop";\n'+script],
        capture_output=True, encoding='utf-8', timeout=25, check=True,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return json.loads(result.stdout.lstrip('\ufeff'))


def task_status():
    names = ','.join("'"+name+"'" for name in TASKS.values())
    return {'tasks': powershell(f'''$rows = @({names} | ForEach-Object {{
        $task = Get-ScheduledTask -TaskName $_ -ErrorAction SilentlyContinue
        if ($task) {{ $info = Get-ScheduledTaskInfo -TaskName $_; @{{name=$_; state=[string]$task.State; last_result=$info.LastTaskResult; next_run=[string]$info.NextRunTime}} }}
        else {{ @{{name=$_; state='Missing'}} }}
    }}); ConvertTo-Json -InputObject $rows -Compress''')}


def sync(mode):
    if mode != 'all' and mode not in TASKS:
        raise ValueError('Unsupported data synchronization action')
    keys = ('daily', 'recent', 'history') if mode == 'all' else (mode,)
    names = ','.join("'"+TASKS[key]+"'" for key in keys)
    with _lock:
        rows = powershell(f'''$rows = @({names} | ForEach-Object {{
            $name = $_
            try {{
                $task = Get-ScheduledTask -TaskName $name
                if ($task.Settings.MultipleInstances -ne 'IgnoreNew') {{ throw 'Unsafe task instance policy' }}
                if ($task.State -eq 'Disabled') {{ throw 'Task is disabled' }}
                if ($task.State -eq 'Running') {{ @{{name=$name; state='already_running'}} }}
                else {{ Start-ScheduledTask -TaskName $name; @{{name=$name; state='requested'}} }}
            }} catch {{ @{{name=$name; state='error'}} }}
        }}); ConvertTo-Json -InputObject $rows -Compress''')
    return dict(tasks=rows, message='已提交同步请求；运行中的任务不重复启动。是否完成以任务状态及新增数据为准。日更仍保留写入互斥，历史分钟仍受额度限制。')
