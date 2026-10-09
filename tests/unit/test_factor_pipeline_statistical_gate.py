"""Keep the full statistical family while avoiding costs for established rejections."""
import datetime as dt
import json
import tomllib
from concurrent.futures import Future

import polars as pl
import pytest

from quant.research import factor_battery_cost_batch as cost_batch
from quant.research import run_factor_pipeline as pipeline
from quant.research.factor_battery_screen import run_screen


CONFIG = '''variants = ["raw", "size_industry_neutral"]
primary_variant = "raw"
[admission]
minimum_months = 96
minimum_absolute_newey_west_t = 3.0
minimum_directional_icir = 0.3
minimum_yearly_positive_fraction = 0.7
minimum_long_short_sharpe = 0.5
minimum_top_net_excess_all_market_ew = 0.0
maximum_absolute_rank_correlation_with_better = 0.7
[multiple_testing]
q = 0.05
admission_requires_fdr = false
[portfolio]
cost_multipliers = [0.5, 1.0, 2.0]
'''


def inputs(tmp_path, monkeypatch, passes=(False, False, False, False)):
    config, library = tmp_path/'battery.toml', tmp_path/'library'
    config.write_text(CONFIG)
    library.mkdir()
    for factor in ('a', 'b'):
        (library/f'{factor}.toml').write_text(
            f'id="{factor}"\nexpr="adj_close"\nfamily="test"\ndirection=1\nsource_ref="fixture"\n')

    def statistics(**kwargs):
        assert kwargs['selected'] == 'all'
        folder = kwargs['output']
        folder.mkdir()
        (folder/'battery.toml').write_text(CONFIG + '\n[run]\nselected="all"\nas_of=2026-08-31\n')
        pl.DataFrame({
            'factor': ['a', 'a', 'b', 'b'],
            'variant': ['raw', 'size_industry_neutral']*2,
            'months': [120]*4,
            'newey_west_t': [4.0 if good else 0.1 for good in passes],
            'icir': [0.6]*4, 'yearly_positive_fraction': [0.9]*4,
            'p_value': [0.001 if good else 0.9 for good in passes],
            'group_statistics': [{'long_short_sharpe': 1.0}]*4,
        }).write_parquet(folder/'statistics.parquet')
        (folder/'summary.json').write_text(json.dumps({'factors': 2, 'variant_rows': 4}))

    monkeypatch.setattr(pipeline, 'run_statistics', statistics)
    return dict(config=config, library=library, as_of=dt.date(2026, 8, 31),
                output=tmp_path/'run', data_root=tmp_path/'data', execution_snapshot='frozen', workers=1)


def forbid_heavy(monkeypatch):
    def forbidden(**kwargs):
        pytest.fail('Statistical rejection must not dispatch account or correlation work')
    for name in ('run_cost_batch', 'run_benchmarks', 'run_redundancy'):
        monkeypatch.setattr(pipeline, name, forbidden)


def test_complete_rejection_keeps_full_bh_and_costs_unknown(tmp_path, monkeypatch):
    args = inputs(tmp_path, monkeypatch)
    forbid_heavy(monkeypatch)
    result = pipeline.run_pipeline(**args)
    frozen = json.loads((args['output']/'pipeline_config.json').read_text())
    assert frozen['cost_statistical_gate'] is True
    assert result['cost_statistical_gate'] is True
    assert result['cost_evaluation_status'] == 'skipped_not_evaluated'
    assert result['statistically_rejected_factors'] == ['a', 'b']
    assert set(result['skipped_work']) == {
        'factor_cost_replays', 'stock_account_benchmarks', 'historical_correlations'}
    screened = pl.read_parquet(args['output']/'screen/statistical_screen.parquet')
    scorecard = pl.read_parquet(result['scorecard_path'])
    assert screened.height == scorecard.height == 4
    assert screened['bh_adjusted_p'].to_list() == [0.9]*4
    assert scorecard['factor_admitted'].to_list() == [False]*4
    assert scorecard['conclusion'].to_list() == ['REJECTED']*4
    assert scorecard['costs_complete'].to_list() == [False]*4
    assert scorecard['cost_excess_pass'].to_list() == [None]*4
    assert not (args['output']/'benchmarks').exists()
    assert not (args['output']/'redundancy').exists()
    assert result['cost_failures'] == result['pending_external_runs'] == {}
    assert pipeline.run_pipeline(**args, resume=True) == result


def test_secondary_pass_keeps_factor_both_versions_and_all_costs(tmp_path, monkeypatch):
    args = inputs(tmp_path, monkeypatch, passes=(False, True, False, False))
    stages, submitted = [], []

    def heavy_stage(**kwargs):
        stages.append(kwargs['output'].name)
        kwargs['output'].mkdir()

    class Pool:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def submit(self, fn, **kwargs):
            assert fn is cost_batch.run_factor_costs
            settings = tomllib.loads((kwargs['statistics']/'battery.toml').read_text())
            submitted.append((kwargs['factor'], settings['variants'], settings['portfolio']['cost_multipliers']))
            future = Future()
            # Simulate completion without running any account; scorecard correctly keeps evidence unknown.
            future.set_result({})
            return future

    monkeypatch.setattr(pipeline, 'run_benchmarks', heavy_stage)
    monkeypatch.setattr(pipeline, 'run_redundancy', heavy_stage)
    monkeypatch.setattr(cost_batch, 'ProcessPoolExecutor', Pool)
    monkeypatch.setattr(cost_batch, 'prepare_plan', lambda *args: None)
    result = pipeline.run_pipeline(**args)
    assert stages == ['benchmarks', 'redundancy']
    assert submitted == [('a', ['raw', 'size_industry_neutral'], [0.5, 1.0, 2.0])]
    assert result['statistically_rejected_factors'] == ['b']
    assert result['skipped_work'] == []
    assert result['scorecard']['statistical_pass_rows'] == 1
    assert result['scorecard']['admission_unresolved_rows'] == 1


@pytest.mark.parametrize('damage', [
    'null', 'integer', 'missing_pass', 'missing_version', 'duplicate', 'empty',
    'statistics_missing_version', 'settings_mismatch', 'summary_missing', 'summary_count',
])
def test_incomplete_or_unknown_screen_never_skips_or_starts_costs(tmp_path, monkeypatch, damage):
    args = inputs(tmp_path, monkeypatch)
    forbid_heavy(monkeypatch)

    def corrupt_screen(**kwargs):
        result = run_screen(**kwargs)
        path = kwargs['output']/'statistical_screen.parquet'
        table = pl.read_parquet(path)
        if damage == 'null':
            table = table.with_columns(pl.Series('statistical_pass', [False, None, False, False]))
        elif damage == 'integer':
            table = table.with_columns(pl.col('statistical_pass').cast(pl.Int64))
        elif damage == 'missing_pass':
            table = table.drop('statistical_pass')
        elif damage == 'missing_version':
            table = table.head(3)
        elif damage == 'duplicate':
            table = pl.concat([table.head(3), table.head(1)])
        elif damage == 'empty':
            table = table.head(0)
        elif damage == 'statistics_missing_version':
            source = kwargs['statistics']/'statistics.parquet'
            pl.read_parquet(source).head(3).write_parquet(source)
        elif damage == 'settings_mismatch':
            with (kwargs['output']/'battery.toml').open('a') as stream:
                stream.write('\n# changed\n')
        elif damage == 'summary_missing':
            (kwargs['output']/'summary.json').unlink()
        elif damage == 'summary_count':
            result['statistical_pass_rows'] = 1
            (kwargs['output']/'summary.json').write_text(json.dumps(result))
        table.write_parquet(path)
        return result

    monkeypatch.setattr(pipeline, 'run_screen', corrupt_screen)
    with pytest.raises((ValueError, FileNotFoundError)):
        pipeline.run_pipeline(**args)
    assert not (args['output']/'summary.json').exists()
    assert not (args['output']/'scorecard').exists()


def test_explicit_existing_runs_preserve_legacy_cost_plan(tmp_path, monkeypatch):
    args = inputs(tmp_path, monkeypatch)
    external = tmp_path/'external'
    calls = []
    for name in ('run_benchmarks', 'run_redundancy'):
        monkeypatch.setattr(pipeline, name, lambda **kwargs: kwargs['output'].mkdir())

    def costs(**kwargs):
        assert kwargs['only_statistical_pass'] is False
        assert kwargs['existing_runs'] == [external]
        calls.append(True)
        return {'completed_runs': {}, 'failures': {}, 'pending_external_runs': {'a': str(external)}}

    monkeypatch.setattr(pipeline, 'run_cost_batch', costs)
    result = pipeline.run_pipeline(**args, existing_runs=[external])
    assert calls == [True]
    assert result['cost_statistical_gate'] is False
    assert result['pending_external_runs'] == {'a': str(external)}
    assert result['skipped_work'] == []
    assert json.loads((args['output']/'pipeline_config.json').read_text())['cost_statistical_gate'] is False
