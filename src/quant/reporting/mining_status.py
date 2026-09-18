"""Explain mining state from live processes, saved checkpoints and scheduler evidence."""
import datetime as dt
import json
import re
import subprocess
from pathlib import Path

ZONE = dt.timezone(dt.timedelta(hours=8))


def instant(value) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(value)
        return parsed.replace(tzinfo=ZONE) if parsed.tzinfo is None else parsed.astimezone(ZONE)
    except (ValueError, TypeError):
        return None


def schedule_snapshot() -> dict:
    script = ("$ErrorActionPreference='Stop'; $t=Get-ScheduledTask -TaskName 'QuantitativeTrading-ContinuousMining'; "
              "$i=$t | Get-ScheduledTaskInfo; [pscustomobject]@{state=[string]$t.State; "
              "next_trigger=$i.NextRunTime.ToString('o'); last_trigger=$i.LastRunTime.ToString('o'); "
              "last_result=$i.LastTaskResult} | ConvertTo-Json -Compress")
    try:
        value = json.loads(subprocess.run(['powershell.exe', '-NoProfile', '-Command', script],
                           capture_output=True, text=True, timeout=10, check=True).stdout)
        if not isinstance(value, dict) or 'state' not in value:
            raise ValueError('Unexpected scheduler response')
        return value
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {'error': type(exc).__name__}


def progress_snapshot(run: Path) -> dict:
    candidates = []
    for name in ('N2/search_progress.json', 'N4/admission_progress.json', 'summary.json'):
        path = run/name
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
            if value:
                candidates.append((path.stat().st_mtime, name, value))
        except (OSError, ValueError):
            pass
    if not candidates:
        return {}
    stamp, name, value = max(candidates, key=lambda row: row[0])
    return {'saved_at': dt.datetime.fromtimestamp(stamp, ZONE).isoformat(timespec='seconds'),
            'source': name, 'generation': value.get('generation'),
            'unique_evaluations': value.get('unique_evaluations')}


def describe(status: dict, scheduler: dict, processes: list[dict], process_error,
             schedule: dict, *, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(ZONE)
    if now.tzinfo is None:
        now = now.replace(tzinfo=ZONE)
    running = [p for p in processes if re.search(
        r'quant(?:\s+research\s+mining\b|\.research\.continuous_mining\b)', p.get('command') or '')]
    state = status.get('state')
    updated, scheduler_at = instant(status.get('updated_at')), instant(scheduler.get('updated_at'))
    fresh_defer = (scheduler.get('status') == 'deferred' and scheduler_at is not None
                   and (updated is None or scheduler_at >= updated))
    retry = instant(status.get('retry_after'))
    if process_error:
        code, label, detail = 'unknown', '状态未知', '进程读取失败，不能据此判断研究已停止。'
    elif running:
        code, label, detail = 'running', '研究运行中', '已检测到持续研究主进程；阶段和计算进度见下方。'
    elif state == 'needs_attention':
        code, label, detail = 'failed', '需要处理故障', '已达到连续失败上限，请检查错误记录后恢复。'
    elif retry and retry > now:
        code, label, detail = 'cooldown', '等待重试', '上次执行失败，正在等待重试冷却结束。'
    elif fresh_defer:
        reason = scheduler.get('reason', '')
        if 'writer' in reason:
            code, label, detail = 'writer_wait', '等待其他写入任务', '数据或模拟账户任务占用写入时段，下次调度会重新检查。'
        elif 'observation' in reason:
            code, label, detail = 'daily_wait', '为每日观察让出时段', '避让记录已保存，下次调度会重新检查。'
        else:
            code, label, detail = 'deferred', '等待调度', reason or '启动器暂缓了本次执行。'
    elif state == 'resumable':
        code, label, detail = 'slice_wait', '时间片结束，等待恢复', '断点已保留，下次调度继续未完成批次。'
    elif state == 'completed':
        code, label, detail = 'batch_wait', '本批完成，等待下一批', '下次调度启动新的研究批次。'
    elif state == 'running':
        code, label, detail = 'interrupted', '进程已退出，等待恢复', '保存状态仍为运行，但本次未检测到研究主进程；退出原因尚未确认。'
    else:
        code, label, detail = 'idle', '等待调度', '当前没有检测到持续研究主进程。'
    trigger = instant(schedule.get('next_trigger'))
    next_trigger = trigger.isoformat(timespec='seconds') if trigger and trigger > now else None
    if schedule.get('state') == 'Disabled':
        next_trigger = None
        detail += ' 计划任务已禁用，无法自动恢复。'
    return {'code': code, 'label': label, 'detail': detail,
            'retry_after': retry.isoformat(timespec='seconds') if retry and retry > now else None,
            'next_trigger': next_trigger,
            'schedule_note': '触发时间不保证开工，仍需检查避让、写入占用和重试条件。',
            'schedule_error': schedule.get('error'), 'scheduler_state': schedule.get('state'),
            'saved_state_at': status.get('updated_at')}
