"""Small, invocation-local progress receipt for the daily input refresh."""
import datetime as dt
import json
import os
from pathlib import Path


class RefreshProgress:
    def __init__(self, path: Path | None):
        self.path = path
        self.state = {'pid': os.getpid(), 'stages': {}}

    def write(self) -> None:
        if self.path is not None:
            self.state['updated_at'] = dt.datetime.now().isoformat()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.state, ensure_ascii=False), encoding='utf-8')
            temporary.replace(self.path)

    def update(self, counts: dict) -> None:
        self.state['counts'] = counts
        self.write()

    def run(self, name, action, **kwargs):
        self.state.update(stage=name, status='running', counts={},
                          started_at=dt.datetime.now().isoformat(),
                          waiting_reason='等待当前数据步骤返回；更新时间不代表进程存活')
        self.write()
        try:
            result = action(**kwargs)
        except Exception as exc:
            # Do not publish provider exception text, which may contain credentials.
            self.state.update(status='failed', error_type=type(exc).__name__,
                              waiting_reason='本步骤失败，详见当次日更日志')
            self.state['stages'][name] = 'failed'
            self.write()
            raise
        partial = isinstance(result, dict) and bool(result.get('errors'))
        status = 'partial' if partial else 'complete'
        self.state.update(status=status, waiting_reason='存在未完成数据请求' if partial else '')
        self.state['stages'][name] = status
        self.write()
        return result
