"""Best-effort scheduler failure alerts through enabled notification channels."""
import argparse
import hashlib
import json
import time
from pathlib import Path

from quant.core.paths import project_paths
from quant.execution.manual_session_service import instance_lock
from quant.notify import send


# Scheduler scripts stay ASCII. Chinese titles are applied here.
TASK_LABELS = {'intel_weekly': '情报周扫描'}


def report(task, code, log, *, root=None, now=None, sender=send):
    folder = root or project_paths().artifacts / 'notify/automation'
    folder.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(task.encode()).hexdigest()[:20]
    state_path = folder / (key+'.json')
    timestamp = time.time() if now is None else now
    with instance_lock(folder/(key+'.lock')):
        state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
        if code == 0:
            state_path.write_text('{}', encoding='utf-8')
            return {'status': 'healthy'}
        if state.get('code') == code and timestamp-state.get('at', 0) < 3600:
            return {'status': 'suppressed', 'reason': 'same task/exit within one hour'}
        # Record the attempt before sending; an ambiguous send is never retried automatically.
        state_path.write_text(json.dumps(dict(task=task, code=code, at=timestamp)), encoding='utf-8')
        label = TASK_LABELS.get(task, task)
        result = sender('自动化异常：'+label,
                        f'任务未正常完成（退出码 {code}）。\n日志：{log}\n同一任务、同一退出码一小时内不重复提醒；请查看日志定位原因。')
        return {'status': 'attempted', 'results': [vars(r) for r in result]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--task', required=True)
    parser.add_argument('--code', required=True, type=int)
    parser.add_argument('--log', required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(report(args.task, args.code, str(args.log)), ensure_ascii=False))
    except Exception as exc:
        # Reporting must never replace the job's own exit code or stop its next step.
        print(json.dumps({'status': 'alert_failed', 'error': type(exc).__name__}))


if __name__ == '__main__':
    main()
