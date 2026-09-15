import datetime as dt
import json

from quant.research import continuous_mining as mining


def config(tmp_path):
    path = tmp_path/'nightly.toml'
    path.write_text('[genetic]\nseed = 10\n', encoding='utf-8')
    return path


def success():
    return {'steps': {step: {'ok': True} for step in ('N1', 'N2', 'N3', 'N4', 'N5')}}


def test_weekly_candidates_run_before_local_research_without_blocking_on_failure(tmp_path, monkeypatch):
    from quant.research import weekly_factor_candidates as weekly
    path = config(tmp_path)
    path.write_text('weekly_candidates_config = "weekly.toml"\n' + path.read_text())
    calls = []
    def generate(config, **kwargs):
        assert kwargs['execute'] is True
        calls.append('weekly')
        raise ValueError('Pricing snapshot requires refresh')
    def execute(*args, **kwargs):
        assert calls == ['weekly']
        return success()
    monkeypatch.setattr(weekly, 'run', generate)
    monkeypatch.setattr(mining.nightly, 'execute', execute)
    result = mining.dispatch(path, tmp_path/'continuous')
    assert result['state'] == 'completed'
    assert result['weekly_candidates']['state'] == 'needs_attention'


def test_cross_day_interruption_resumes_same_frozen_batch(tmp_path, monkeypatch):
    path, root = config(tmp_path), tmp_path/'continuous'
    calls = []

    def execute(frozen, **kwargs):
        calls.append((frozen, kwargs))
        run = kwargs['run_path']
        checkpoint = run/'checkpoint.json'
        if len(calls) == 1:
            checkpoint.write_text('retained')
            raise KeyboardInterrupt()
        assert checkpoint.read_text() == 'retained'
        assert 'seed = 11' in frozen.read_text()
        return success()

    monkeypatch.setattr(mining.nightly, 'execute', execute)
    import pytest
    with pytest.raises(KeyboardInterrupt):
        mining.dispatch(path, root, now=dt.datetime(2026, 9, 14, 12))
    path.write_text('[genetic]\nseed = 99\n')
    result = mining.dispatch(path, root, now=dt.datetime(2026, 9, 16, 12))
    assert result['state'] == 'completed'
    assert calls[0][0] == calls[1][0]
    assert calls[1][1]['session_hours'] == 2


def test_completed_batch_advances_with_new_seed(tmp_path, monkeypatch):
    def execute(frozen, **kwargs):
        result = success()
        (kwargs['run_path']/'summary.json').write_text(json.dumps(result))
        return result
    monkeypatch.setattr(mining.nightly, 'execute', execute)
    path, root = config(tmp_path), tmp_path/'continuous'
    first = mining.dispatch(path, root)
    second = mining.dispatch(path, root)
    assert first['seed'] == 11
    assert second['seed'] == 12
    assert first['run'] != second['run']


def test_interrupted_batch_creation_is_not_published(tmp_path, monkeypatch):
    root = tmp_path/'continuous'
    partial = root/'batch_000001.2026-09-14.pending'
    (partial/'2026-09-14').mkdir(parents=True)
    monkeypatch.setattr(mining.nightly, 'execute', lambda *a, **k: success())
    result = mining.dispatch(config(tmp_path), root, now=dt.datetime(2026, 9, 16))
    assert result['state'] == 'completed'
    assert result['batch'] == 'batch_000001'
    assert result['run'].endswith('2026-09-16')
    assert partial.exists()


def test_failure_cools_down_then_stops_retries(tmp_path, monkeypatch):
    calls = []
    def execute(*args, **kwargs):
        calls.append(1)
        return {'steps': {'N2': {'ok': False, 'error': 'N2 exit=1; see process.log'}}}
    monkeypatch.setattr(mining.nightly, 'execute', execute)
    path, root = config(tmp_path), tmp_path/'continuous'
    start = dt.datetime(2026, 9, 14, 12)
    assert mining.dispatch(path, root, now=start)['state'] == 'cooldown'
    mining.dispatch(path, root, now=start+dt.timedelta(minutes=10))
    assert len(calls) == 1
    mining.dispatch(path, root, now=start+dt.timedelta(hours=1))
    assert mining.dispatch(path, root, now=start+dt.timedelta(hours=2))['state'] == 'needs_attention'
    mining.dispatch(path, root, now=start+dt.timedelta(days=1))
    assert len(calls) == 3


def test_time_slice_is_resumable_not_repeated_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(mining.nightly, 'execute', lambda *a, **k: {'steps': {
        'N2': {'ok': False, 'error': 'Worker exceeded 7200 seconds'},
        'N3': {'ok': False, 'error': 'Time/disk guard: -2s, 100.0 GiB'},
        'N4': {'ok': False, 'error': 'N3 did not complete'}}})
    path, root = config(tmp_path), tmp_path/'continuous'
    for _ in range(4):
        assert mining.dispatch(path, root)['state'] == 'resumable'


def test_explicit_session_resumes_expired_run_without_changing_default(tmp_path, monkeypatch):
    from quant.factors import library
    from quant.research import nightly, nightly_steps
    monkeypatch.setattr(library, 'load_library', lambda _: [])
    monkeypatch.setattr(nightly_steps, 'resolve_settings', lambda s, _: s)
    monkeypatch.setattr(nightly, 'work_order', lambda *_: ())
    monkeypatch.setattr(nightly, 'digest', lambda *_: None)
    path = tmp_path/'config.toml'
    path.write_text('output_root="unused"\nlibrary="unused"\nweekday_hours=6\nweekend_hours=20\n')
    run = tmp_path/'2026-09-14'
    run.mkdir()
    (run/'summary.json').write_text(json.dumps({'started_at': '2026-09-14T00:00:00',
        'deadline_at': '2026-09-14T06:00:00', 'steps': {}, 'library_before': 0}))
    result = nightly.execute(path, now=dt.datetime(2026, 9, 16, 10), run_path=run, session_hours=2)
    assert result['started_at'] == '2026-09-14T00:00:00'
    assert result['deadline_at'] == '2026-09-16T12:00:00'
