import datetime as dt
import json
import time
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest

from quant.research import factor_battery_cost_batch as batch
from quant.research import factor_cost_reuse as reuse
from quant.research.factor_battery_cost_report import load_cost_history


@pytest.fixture
def case(tmp_path, monkeypatch):
    statistics, screen, output = [tmp_path/name for name in ('statistics', 'screen', 'costs')]
    config = ('primary_variant="raw"\nvariants=["raw"]\n[run]\nas_of=2020-01-31\n'
              '[portfolio]\ncost_multipliers=[0.5,1.0,2.0]\n')
    for folder in (statistics, screen):
        folder.mkdir()
        (folder/'battery.toml').write_text(config)
    table = pl.DataFrame({'factor': ['a', 'b', 'c'], 'variant': ['raw']*3,
                          'statistical_pass': [True]*3, 'icir': [.3, .2, .1]})
    table.write_parquet(statistics/'statistics.parquet')
    table.write_parquet(screen/'statistical_screen.parquet')
    for factor in ('a', 'b', 'c'):
        folder = statistics/'factors'/factor
        folder.mkdir(parents=True)
        (folder/'statistics.json').write_text(json.dumps({'definition': {'id': factor, 'direction': 1}}))
        pl.DataFrame({'trade_date': [dt.date(2020, 1, 31)]*2, 'symbol': ['x', 'y'],
                      'raw': [1., 2.] if factor != 'c' else [2., 1.]}).write_parquet(folder/'monthly_scores.parquet')
    calls = []

    def replay(**kwargs):
        factor, folder = kwargs['factor'], kwargs['output']
        calls.append(factor)
        folder.mkdir()
        (folder/'battery.toml').write_text(config+f'[cost_replay]\nfactor="{factor}"\nexecution_snapshot="fixture"\n')
        (folder/'share_exchanges.toml').write_text(
            Path('configs/data/share_exchanges_20260912.toml').read_text(encoding='utf-8'), encoding='utf-8')
        (folder/'replay_config.json').write_text(json.dumps({'data_root': str(tmp_path.resolve()), 'snapshot': 'fixture'}))
        rows = []
        for cost in [.5, 1., 2.]:
            year = folder/'raw'/f'cost_{cost:g}'/'2020'
            year.mkdir(parents=True)
            frame = pl.DataFrame({'strategy': [f'battery_{factor}_raw'], 'date': [dt.date(2020, 1, 31)], 'equity': [100.]})
            for name in ('nav', 'trades', 'rejections'):
                frame.write_parquet(year/f'{name}.parquet')
            rows.append({'factor': factor, 'variant': 'raw', 'cost_multiplier': cost})
        (folder/'summary.json').write_text(json.dumps({'factor': factor, 'execution_snapshot': 'fixture', 'rows': rows}))

    class Pool:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def submit(self, fn, **kwargs):
            future = Future()
            try:
                replay(**kwargs)
                future.set_result({})
            except Exception as exc:
                future.set_exception(exc)
            return future

    monkeypatch.setattr(batch, 'ProcessPoolExecutor', Pool)
    return dict(statistics=statistics, screen=screen, output=output, data_root=tmp_path,
                execution_snapshot='fixture', existing_runs=[], workers=1, deduplicate=True), calls


def test_dispatches_only_representatives_and_publishes_readable_alias(case):
    args, calls = case
    result = batch.run_cost_batch(**args)
    assert calls == ['a', 'c']
    assert result['reused_factors'] == {'b': 'a'}
    assert result['saved_variant_cost_replays'] == 3
    assert not result['failures'] and len(result['completed_runs']) == 3
    nav, _ = load_cost_history(args['output']/'b', 'raw', 1., dt.date(2020, 1, 31))
    assert nav['strategy'].to_list() == ['battery_b_raw']
    assert not (args['output']/'b/replay_config.json').exists()
    assert batch.run_cost_batch(**args, resume=True)['reused_factors'] == {'b': 'a'}
    assert calls == ['a', 'c']
    (args['output']/'b/raw/cost_1/2020/nav.parquet').write_bytes(b'broken')
    with pytest.raises(ValueError, match='incomplete or changed'):
        batch.run_cost_batch(**args, resume=True)


def test_interrupted_publication_rebuilds_without_replaying_representatives(case, monkeypatch):
    args, calls = case
    original = Path.rename
    def interrupted(path, target):
        if path.parent.name == 'reuse_staging':
            raise OSError('simulated interruption before publication')
        return original(path, target)
    monkeypatch.setattr(Path, 'rename', interrupted)
    result = batch.run_cost_batch(**args)
    assert set(result['failures']) == {'b'}
    assert not (args['output']/'b').exists()
    monkeypatch.setattr(Path, 'rename', original)
    result = batch.run_cost_batch(**args, resume=True)
    assert not result['failures'] and calls == ['a', 'c']
    assert result['saved_variant_cost_replays'] == 3


def test_changed_signal_cannot_resume_old_plan(case):
    args, _ = case
    batch.run_cost_batch(**args)
    path = args['statistics']/'factors/b/monthly_scores.parquet'
    pl.read_parquet(path).with_columns(-pl.col('raw')).write_parquet(path)
    with pytest.raises(ValueError, match='Frozen replay reuse inputs changed'):
        batch.run_cost_batch(**args, resume=True)


def test_incomplete_representative_costs_never_publish_alias(case):
    args, calls = case
    batch.run_cost_batch(**args)
    source = args['output']/'a/summary.json'
    result = json.loads(source.read_text())
    result['rows'].pop()
    source.write_text(json.dumps(result))
    next_args = {**args, 'output': args['output'].with_name('next'),
                 'existing_runs': [args['output']/'a', args['output']/'c']}
    result = batch.run_cost_batch(**next_args)
    assert set(result['failures']) == {'b'}
    assert 'incomplete' in result['failures']['b']
    assert not (next_args['output']/'b').exists()
    assert result['saved_variant_cost_replays'] == 0 and calls == ['a', 'c']


def _files(folder):
    return {path.relative_to(folder).as_posix(): path.read_bytes()
            for path in folder.rglob('*') if path.is_file()}


@pytest.mark.parametrize('winerror', [5, 32, 33])
@pytest.mark.parametrize('persistent', [False, True])
def test_alias_publication_retries_without_replaying_or_mutating_staging(
        case, monkeypatch, winerror, persistent):
    args, calls = case
    rename = Path.rename
    stages, sleeps = [], []

    def blocked(stage, target):
        if stage.parent.name == 'reuse_staging':
            stages.append(_files(stage))
            if persistent or len(stages) <= 2:
                exc = PermissionError('fixture Windows reader')
                exc.winerror = winerror
                raise exc
        return rename(stage, target)

    def wait(delay):
        sleeps.append(delay)
        time.sleep(delay)

    monkeypatch.setattr(Path, 'rename', blocked)
    monkeypatch.setattr(reuse, 'time', SimpleNamespace(sleep=wait))
    result = batch.run_cost_batch(**args)
    assert calls == ['a', 'c']
    assert stages and all(stage == stages[0] for stage in stages)
    assert sleeps == [0.05 * i for i in range(1, len(stages))]
    stage = args['output']/'reuse_staging/b'
    target = args['output']/'b'
    if persistent:
        assert len(stages) == 10 and len(sleeps) == 9
        assert set(result['failures']) == {'b'}
        assert not target.exists() and _files(stage) == stages[0]
        assert result['saved_variant_cost_replays'] == 0
    else:
        assert 3 <= len(stages) <= 10
        assert not result['failures'] and result['reused_factors'] == {'b': 'a'}
        assert result['saved_variant_cost_replays'] == 3
        assert not stage.exists() and _files(target) == stages[0]
        for cost in (0.5, 1., 2.):
            nav, _ = load_cost_history(target, 'raw', cost, dt.date(2020, 1, 31))
            assert nav['strategy'].to_list() == ['battery_b_raw']


@pytest.mark.parametrize('kind', ['unknown_permission', 'other_os_error', 'target_appears'])
def test_alias_publication_does_not_retry_other_errors_or_replace_new_target(case, monkeypatch, kind):
    args, calls = case
    rename = Path.rename
    attempted, sleeps = [], []

    def blocked(stage, target):
        if stage.parent.name != 'reuse_staging':
            return rename(stage, target)
        attempted.append(_files(stage))
        if kind == 'target_appears':
            target.mkdir()
            (target/'sentinel').write_bytes(b'another publication')
            exc = PermissionError('fixture concurrent publication')
            exc.winerror = 5
            raise exc
        if kind == 'unknown_permission':
            raise PermissionError('fixture non-Windows permission failure')
        raise OSError('fixture unrelated filesystem error')

    monkeypatch.setattr(Path, 'rename', blocked)
    monkeypatch.setattr(reuse, 'time', SimpleNamespace(sleep=sleeps.append))
    result = batch.run_cost_batch(**args)
    assert calls == ['a', 'c']
    assert len(attempted) == 1 and sleeps == []
    assert set(result['failures']) == {'b'} and result['saved_variant_cost_replays'] == 0
    assert _files(args['output']/'reuse_staging/b') == attempted[0]
    target = args['output']/'b'
    if kind == 'target_appears':
        assert _files(target) == {'sentinel': b'another publication'}
    else:
        assert not target.exists()
