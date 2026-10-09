import json
import sys
import tomllib
from pathlib import Path

import polars as pl
import pytest

from quant.research.factor_battery_cost_batch import cost_order, existing_cost_factor, run_cost_batch
from quant.research import factor_battery_cost_batch as batch_module
from quant.research.factor_battery_costs import NoExecutableTopGroup


@pytest.mark.parametrize('error,passes,expected', [
    (NoExecutableTopGroup('empty'), [False, False], True),
    (NoExecutableTopGroup('empty'), [False, True], False),
    (NoExecutableTopGroup('empty'), [False, None], False),
    (ValueError('Factor has no executable top-group observations'), [False, False], False),
    (OSError('missing panel'), [False, False], False),
])
def test_empty_cost_rejection_does_not_swallow_other_failures(error, passes, expected):
    table = pl.DataFrame({'factor': ['a', 'a'], 'statistical_pass': passes})
    assert batch_module.terminal_cost_rejection(error, table, 'a') is expected
    assert not batch_module.terminal_cost_rejection(error, table, 'unknown')


@pytest.mark.parametrize('state', ['complete', 'failed', 'pending'])
def test_cli_exit_status_preserves_batch_result_and_resume(monkeypatch, capsys, state):
    result = {'completed_runs': {'done': 'saved'},
              'failures': {'failed': 'missing inputs'} if state == 'failed' else {},
              'pending_external_runs': {'waiting': 'external'} if state == 'pending' else {}}

    def run(**kwargs):
        assert kwargs['resume'] is True
        assert kwargs['existing_runs'] == [Path('external')]
        return result

    monkeypatch.setattr(batch_module, 'run_cost_batch', run)
    monkeypatch.setattr(sys, 'argv', ['cost_batch', '--statistics', 'statistics', '--screen', 'screen',
                                    '--output', 'output', '--execution-snapshot', 'snapshot',
                                    '--existing-run', 'external', '--resume'])
    if state == 'complete':
        batch_module.main()
    else:
        with pytest.raises(SystemExit) as error:
            batch_module.main()
        assert error.value.code == 1
    assert json.loads(capsys.readouterr().out) == result


def test_cost_order_prioritizes_passes_then_primary_icir_and_keeps_rejections():
    table = pl.DataFrame({'factor': ['b', 'a', 'c', 'd'], 'variant': ['neutral']*4,
                          'statistical_pass': [True, True, False, False], 'icir': [.5, .5, .9, None]})
    assert cost_order(table, primary='neutral') == ['a', 'b', 'c', 'd']


def test_inflight_cost_run_is_reserved_and_incompatible_snapshot_rejected(tmp_path):
    config = Path('configs/factors/battery.toml').read_bytes()
    config += b'\n[run]\nas_of = 2026-08-31\nselected = "all"\n'
    settings = tomllib.loads(config.decode())
    (tmp_path/'battery.toml').write_bytes(config+b'\n[cost_replay]\nfactor = "sample"\nexecution_snapshot = "fixture"\n')
    assert existing_cost_factor(tmp_path, settings=settings, snapshot='fixture') == 'sample'
    assert not (tmp_path/'summary.json').exists()
    with pytest.raises(ValueError, match='different settings'):
        existing_cost_factor(tmp_path, settings=settings, snapshot='other')


def test_cost_batch_rejects_a_screen_missing_registered_rows(tmp_path):
    statistics, screen = tmp_path/'statistics', tmp_path/'screen'
    statistics.mkdir()
    screen.mkdir()
    config = Path('configs/factors/battery.toml').read_bytes()
    (statistics/'battery.toml').write_bytes(config)
    (screen/'battery.toml').write_bytes(config)
    expected = pl.DataFrame({'factor': ['a', 'a'], 'variant': ['raw', 'size_industry_neutral']})
    expected.write_parquet(statistics/'statistics.parquet')
    expected.head(1).write_parquet(screen/'statistical_screen.parquet')
    with pytest.raises(ValueError, match='cannot omit'):
        run_cost_batch(statistics=statistics, screen=screen, output=tmp_path/'output', data_root=tmp_path,
                       execution_snapshot='fixture', existing_runs=[], workers=1)


def test_statistical_rejection_skips_cost_work_after_full_family_validation(tmp_path):
    statistics, screen = tmp_path/'statistics', tmp_path/'screen'
    statistics.mkdir()
    screen.mkdir()
    config = Path('configs/factors/battery.toml').read_bytes()
    (statistics/'battery.toml').write_bytes(config)
    (screen/'battery.toml').write_bytes(config)
    table = pl.DataFrame({'factor': ['a', 'a'], 'variant': ['raw', 'size_industry_neutral'],
                          'statistical_pass': [False, False], 'icir': [.1, .2]})
    table.select('factor', 'variant').write_parquet(statistics/'statistics.parquet')
    table.write_parquet(screen/'statistical_screen.parquet')
    result = run_cost_batch(statistics=statistics, screen=screen, output=tmp_path/'output',
        data_root=tmp_path, execution_snapshot='fixture', existing_runs=[], workers=1,
        only_statistical_pass=True)
    assert result['factors'] == 0 and result['statistically_rejected_factors'] == ['a']
    assert result['completed_runs'] == result['failures'] == {}


@pytest.mark.parametrize('required', [None, ['checkpointed', 'fresh']])
def test_explicit_batch_resume_only_dispatches_checkpointed_local_partials(tmp_path, monkeypatch, required):
    from concurrent.futures import Future
    from quant.research import factor_battery_cost_batch as module

    statistics, screen, output = (tmp_path / name for name in ('statistics', 'screen', 'output'))
    config = 'primary_variant = "raw"\n'
    for folder in (statistics, screen, output):
        folder.mkdir()
        (folder / 'battery.toml').write_text(config)
    table = pl.DataFrame({'factor': ['checkpointed', 'old', 'fresh'], 'variant': ['raw'] * 3,
                          'statistical_pass': [False] * 3, 'icir': [.3, .2, .1]})
    table.select('factor', 'variant').write_parquet(statistics / 'statistics.parquet')
    table.write_parquet(screen / 'statistical_screen.parquet')
    for factor in ('checkpointed', 'old'):
        folder = output / factor
        folder.mkdir()
        (folder / 'battery.toml').write_text(config +
            f'[cost_replay]\nfactor = "{factor}"\nexecution_snapshot = "fixture"\n')
    (output / 'checkpointed/replay_config.json').write_text('{}')
    calls = []

    class Pool:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def submit(self, fn, **kwargs):
            calls.append((kwargs['factor'], kwargs['resume']))
            future = Future()
            future.set_result({})
            return future

    monkeypatch.setattr(module, 'ProcessPoolExecutor', Pool)
    result = run_cost_batch(statistics=statistics, screen=screen, output=output, data_root=tmp_path,
        execution_snapshot='fixture', existing_runs=[], workers=1, resume=True, required_factors=required)
    assert calls == [('checkpointed', True), ('fresh', False)]
    assert set(result['failures']) == ({'old'} if required is None else set())
    assert (output / 'old/battery.toml').is_file()
