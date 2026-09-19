import datetime as dt
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.request import urlopen

import pytest

from quant.data.refresh_progress import RefreshProgress
from quant.reporting.dashboard_cache import SnapshotCache
from quant.research import nightly_monthly, nightly_steps
from quant.research.slice_budget import SliceYield


def test_resumed_old_batch_uses_scheduler_month_and_completed_session(tmp_path, monkeypatch):
    from quant.data import refresh
    monkeypatch.setattr(refresh, 'latest_session', lambda **kw: dt.date(2026, 9, 30))
    calls = []
    monkeypatch.setattr(nightly_monthly, '_run_month', lambda settings, output: calls.append((settings, output)))
    settings = {'output_root': str(tmp_path), 'monthly_first_period': '2026-10',
                'scheduler_day': '2026-10-03', 'as_of': dt.date(2026, 8, 31), 'data_root': 'unused'}
    nightly_monthly.monthly_models(settings, tmp_path/'2026-09-29')
    assert calls[0][0]['as_of'] == dt.date(2026, 9, 30)
    assert calls[0][1].name == '2026-10'
    assert settings['as_of'] == dt.date(2026, 8, 31)


def test_admission_reference_never_reads_a_future_cutoff(tmp_path):
    settings = {'output_root': str(tmp_path), 'as_of': dt.date(2026, 8, 31),
                'reference_statistics': 'frozen'}
    for period, date in [('2026-09', '2026-08-31'), ('2026-10', '2026-09-30')]:
        folder = tmp_path/'monthly'/period
        folder.mkdir(parents=True)
        (folder/'battery.toml').write_text('[run]\nas_of='+date)
        (folder/'scorecard.parquet').write_bytes(b'fixture')
        (folder/'summary.json').write_text(json.dumps({'completed': True, 'as_of': date,
            'reference_statistics': str(folder), 'reference_scorecard': str(folder/'scorecard.parquet')}))
    assert nightly_steps.admission_reference(settings)['reference_statistics'].endswith('2026-09')
    assert nightly_steps.admission_reference({**settings, 'as_of': dt.date(2026, 7, 31)})['reference_statistics'] == 'frozen'


def test_due_month_gets_one_recovery_opportunity_without_disabling_failure_limit(tmp_path, monkeypatch):
    from tests.unit.test_continuous_mining import config
    from quant.research import continuous_mining as mining
    calls = []
    def fail(*args, **kwargs):
        calls.append(1)
        return {'steps': {'N3': {'ok': False, 'error': 'fixture failure'}}}
    monkeypatch.setattr(mining.nightly, 'execute', fail)
    path = config(tmp_path)
    path.write_text(f'output_root={json.dumps(str(tmp_path/"nightly"))}\nmonthly_first_period="2026-10"\n'+path.read_text())
    root = tmp_path/'continuous'
    for hour in (1, 3, 5):
        mining.dispatch(path, root, now=dt.datetime(2026, 10, 2, hour))
    assert len(calls) == 3
    mining.dispatch(path, root, now=dt.datetime(2026, 10, 2, 7))
    assert len(calls) == 3
    mining.dispatch(path, root, now=dt.datetime(2026, 10, 3, 7))
    assert len(calls) == 4
    mining.dispatch(path, root, now=dt.datetime(2026, 10, 3, 9))
    assert len(calls) == 4


def test_cached_monthly_skip_reopens_on_current_day(tmp_path, monkeypatch):
    from quant.research import nightly
    from quant.factors import library
    monkeypatch.setattr(library, 'load_library', lambda _: [])
    monkeypatch.setattr(nightly_steps, 'resolve_settings', lambda settings, _: settings)
    monkeypatch.setattr(nightly, 'digest', lambda *_: None)
    monkeypatch.setattr(nightly, 'work_order', lambda *_: ('N5',))
    config = tmp_path/'config.toml'
    config.write_text(f'output_root={json.dumps(str(tmp_path/"monthly_root"))}\n'
        'monthly_first_period="2026-10"\nlibrary="unused"\nweekday_hours=6\nweekend_hours=20\n'
        'minimum_free_gb=0\n[step_timeout_seconds]\nN5=300\n')
    run = tmp_path/'2026-09-29'
    (run/'N5').mkdir(parents=True)
    (run/'N5/result.json').write_text('{"skipped":true}')
    calls = []
    def worker(command, **kwargs):
        calls.append(kwargs['env']['QUANT_SCHEDULER_DAY'])
        (run/'N5/result.json').write_text('{"completed":true,"period":"2026-10"}')
        return object()
    monkeypatch.setattr(nightly.subprocess, 'Popen', worker)
    monkeypatch.setattr(nightly, 'wait_bounded', lambda *a, **kw: 0)
    result = nightly.execute(config, run_path=run, now=dt.datetime(2026, 10, 3, 8), session_hours=2)
    assert calls == ['2026-10-03']
    assert result['steps']['N5']['result']['completed']
    assert len(list((run/'N5').glob('result_before_month_*.json'))) == 1


def test_new_batch_prepares_inputs_once_and_resume_keeps_frozen_paths(tmp_path, monkeypatch):
    from quant.data import nightly_month_inputs, nightly_genetic_inputs
    run = tmp_path/'2026-10-01'
    (run/'candidates').mkdir(parents=True)
    (run/'candidates/x.toml').write_text('id="x"\nexpr="adj_close"\nfamily="price"\ndirection=1\nsource_ref="fixture"\n')
    settings = {'as_of': dt.date(2026, 9, 30), 'training_end': dt.date(2025, 12, 31),
                'history_start': dt.date(2010, 1, 1), 'batch_root': str(tmp_path/'batches'),
                'prepare_month_inputs': True, 'execution_snapshot': 'old', 'data_root': str(tmp_path/'data')}
    prepared = []
    def prepare(**kwargs):
        prepared.append(kwargs['as_of'])
        return {**kwargs['settings'], 'execution_snapshot': 'extended'}
    def coverage(root, snapshot, as_of):
        assert snapshot == 'extended'
        raise ValueError('fixture stops before computation')
    monkeypatch.setattr(nightly_month_inputs, 'ensure_nightly_month_inputs', prepare)
    monkeypatch.setattr(nightly_genetic_inputs, 'require_execution_coverage', coverage)
    for _ in range(2):
        with pytest.raises(ValueError, match='fixture stops'):
            nightly_steps.evaluate(settings, run)
    assert prepared == [dt.date(2026, 9, 30)]
    assert settings['execution_snapshot'] == 'old'


def test_soft_deadline_retains_completed_year_and_resumes_identically(tmp_path, monkeypatch):
    from tests.unit.test_factor_cost_checkpoint import setup_run
    from quant.research import factor_battery_costs as costs
    _, _, kwargs = setup_run(monkeypatch, tmp_path/'run')
    original = costs.save_year
    saved = []

    def save(folder, **values):
        original(folder, **values)
        saved.append(folder)
        monkeypatch.setenv('QUANT_SLICE_SOFT_DEADLINE', '1')

    monkeypatch.setattr(costs, 'save_year', save)
    with pytest.raises(SliceYield):
        costs.run_cost_plans(**kwargs)
    assert len(saved) == 1
    before = {p: p.read_bytes() for p in saved[0].iterdir()}
    monkeypatch.delenv('QUANT_SLICE_SOFT_DEADLINE')
    monkeypatch.setattr(costs, 'save_year', original)
    resumed = costs.run_cost_plans(**kwargs, resume=True)
    assert all(p.read_bytes() == content for p, content in before.items())
    _, _, fresh = setup_run(monkeypatch, tmp_path/'fresh')
    assert resumed['rows'] == costs.run_cost_plans(**fresh)['rows']


def test_cooperative_yield_does_not_accumulate_failures(tmp_path, monkeypatch):
    from tests.unit.test_continuous_mining import config
    from quant.research import continuous_mining as mining
    monkeypatch.setattr(mining.nightly, 'execute', lambda *a, **kw: {'steps': {
        'N3': {'ok': False, 'error': 'Time slice yielded; retained account'},
        'N4': {'ok': False, 'error': 'N3 did not complete'}}})
    path = config(tmp_path)
    for _ in range(4):
        assert mining.dispatch(path, tmp_path/'continuous')['state'] == 'resumable'


def test_progress_records_counts_and_safe_failure_without_claiming_complete(tmp_path):
    path = tmp_path/'progress.json'
    progress = RefreshProgress(path)

    def failing():
        progress.update({'completed': 3, 'total': 10, 'failed': 1})
        raise ValueError('secret=fixture')

    with pytest.raises(ValueError):
        progress.run('minutes', failing)
    row = json.loads(path.read_text())
    assert row['status'] == row['stages']['minutes'] == 'failed'
    assert row['counts']['completed'] == 3
    assert 'secret' not in path.read_text()
    progress.run('quality', lambda: {'errors': ['missing']})
    assert json.loads(path.read_text())['status'] == 'partial'


def test_concurrent_forced_status_refresh_is_single_flight():
    entered, release = threading.Event(), threading.Event()
    calls = []

    def slow():
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return {'value': len(calls)}

    cache = SnapshotCache(slow)
    second_waiting = threading.Event()
    class ObservedLock:
        def __init__(self):
            self.lock = threading.Lock()
            self.attempts = 0
        def __enter__(self):
            self.attempts += 1
            if self.attempts == 2:
                second_waiting.set()
            self.lock.acquire()
        def __exit__(self, *_):
            self.lock.release()
    cache.lock = ObservedLock()
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(cache.get, force=True)
        assert entered.wait(5)
        second_entered = threading.Event()
        def second_read():
            second_entered.set()
            return cache.get(force=True)
        second = pool.submit(second_read)
        assert second_entered.wait(5)
        assert second_waiting.wait(5)
        release.set()
        assert first.result()['value'] == second.result()['value'] == 1
    assert len(calls) == 1


def test_failed_refresh_labels_retained_snapshot_stale():
    cache = SnapshotCache(lambda: {'value': 1})
    cache.get()
    def fail():
        raise OSError('unavailable')
    cache.reader = fail
    result = cache.get(force=True)
    assert result['value'] == 1 and result['cache']['stale']
    assert result['cache']['saved_at']


def test_health_responds_while_status_is_blocked(monkeypatch):
    from quant.reporting import research_dashboard as dashboard
    entered, release = threading.Event(), threading.Event()
    def slow():
        entered.set()
        assert release.wait(10)
        return {'value': 1}
    monkeypatch.setattr(dashboard, 'snapshot', slow)
    server = dashboard.create_server(0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    try:
        with ThreadPoolExecutor(1) as pool:
            status = pool.submit(lambda: urlopen(url+'/api/status', timeout=10).read())
            assert entered.wait(5)
            with urlopen(url+'/api/health', timeout=2) as response:
                assert json.load(response)['service'] == 'quant-research-dashboard'
            release.set()
            assert json.loads(status.result())['value'] == 1
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(3)
