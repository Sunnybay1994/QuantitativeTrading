from types import SimpleNamespace

from quant.reporting.mining_control import authorized, resume


def test_control_requires_local_origin_and_unforgeable_token():
    headers = {'Host': '127.0.0.1:8768', 'Origin': 'http://127.0.0.1:8768',
               'X-Mining-Token': 'secret', 'Content-Length': '0'}
    assert authorized(headers, 'secret', 8768)
    for update in ({'Origin': 'https://evil.test'}, {'Host': 'evil.test:8768'},
                   {'X-Mining-Token': ''}, {'Content-Length': '1'}, {'Transfer-Encoding': 'chunked'}):
        assert not authorized(headers | update, 'secret', 8768)


def test_resume_calls_only_fixed_task_and_preserves_running_result(monkeypatch):
    def run(command, **kwargs):
        assert 'Start-ScheduledTask' in command[-1]
        assert 'IgnoreNew' in command[-1]
        assert 'Stop-Process' not in command[-1]
        assert kwargs['timeout'] == 20
        return SimpleNamespace(stdout='{"state":"already_running","pids":[123]}')
    monkeypatch.setattr('quant.reporting.mining_control.subprocess.run', run)
    assert resume()['pids'] == [123]
