import json

import polars as pl
from polars.testing import assert_frame_equal
import pytest

from quant.research.classic_monthly_baseline import replay
from quant.research.run_multifactor_replay import prepare_constraints
from tests.unit.test_factor_cost_checkpoint import DAYS, scenario, setup_run
from quant.research import factor_battery_costs as costs


def test_none_and_unapplied_hook_keep_default_replay_identical():
    source = scenario()
    original = replay(**source, sessions=DAYS, name='probe', validate_once=True)
    records = []
    def identity(batch, state):
        return batch, {'as_of': str(batch['as_of'][0]), 'feasible': True, 'applied': False}
    transformed = replay(**source, sessions=DAYS, name='probe', validate_once=True,
        target_constraints=identity, constraint_records=records)
    for a, b in zip(original, transformed):
        assert_frame_equal(a, b, check_exact=True)
    assert not records


def test_failed_constraint_preserves_annual_checkpoint_and_reason(tmp_path, monkeypatch):
    _, reads, kwargs = setup_run(monkeypatch, tmp_path/'run')
    kwargs['settings'] = {**kwargs['settings'], 'target_constraints_config': 'fixture'}
    def reject(batch, state):
        return batch, {'as_of': str(batch['as_of'][0]), 'feasible': batch['execution_date'][0].year == 2020,
            'applied': batch['execution_date'][0].year == 2021, 'failure_reason': 'fixture_industry_capacity'}
    with pytest.raises(ValueError, match='Portfolio constraints failed'):
        costs.run_cost_plans(**kwargs, target_constraints=reject)
    folder = kwargs['output']/'raw/cost_0.5'
    account_bytes = (folder/'2020/account.json').read_bytes()
    assert not (folder/'2021/account.json').exists()
    failure = next(folder.glob('constraints_failure_2021_*.json'))
    saved = json.loads(failure.read_text())
    assert saved['diagnostics'][-1]['feasible'] is False
    assert 'fixture_industry_capacity' in saved['reason']
    assert failure.with_suffix('.parquet').is_file()
    reads.clear()
    with pytest.raises(ValueError, match='Portfolio constraints failed'):
        costs.run_cost_plans(**kwargs, target_constraints=reject, resume=True)
    assert reads == [2021]
    assert (folder/'2020/account.json').read_bytes() == account_bytes
    with pytest.raises(ValueError, match='explicit replay configuration'):
        costs.run_cost_plans(**kwargs, resume=True)


def test_constraint_resume_rejects_changed_frozen_controls(tmp_path, monkeypatch):
    from quant.data import equal_weight_index, factor_battery_inputs
    source = scenario()
    dates = source['targets']['as_of'].unique().sort()
    universe = pl.DataFrame({'trade_date': dates, 'symbol': ['A']*len(dates),
        'eligible': [True]*len(dates), 'industry_l1': ['X']*len(dates),
        'total_market_value': [1e9]*len(dates), 'amount20': [1e8]*len(dates),
        'traded': [True]*len(dates), 'limits_known': [True]*len(dates), 'away_from_limits': [True]*len(dates)})
    benchmark = universe.select(pl.col('trade_date').alias('as_of'), 'symbol').with_columns(pl.lit(1.).alias('weight'))
    monkeypatch.setattr(factor_battery_inputs, 'read_frozen_battery_universe', lambda **kw: universe)
    monkeypatch.setattr(equal_weight_index, 'read_equal_weight_targets', lambda **kw: benchmark)
    config = tmp_path/'config.toml'
    config.write_text('auto_trade=false\nmode="research_only"\nstrategy_names=["probe"]\n'
        'statistics="fixture"\nbenchmark_snapshot="fixture"\nbenchmark="all_market_equal_weight"\n')
    output = tmp_path/'output'
    output.mkdir()
    kwargs = dict(config=config, plans={'raw': ('probe', source['targets'])}, data_root=tmp_path, output=output)
    prepare_constraints(**kwargs, resume=False)
    prepare_constraints(**kwargs, resume=True)
    universe = universe.with_columns(pl.lit(2e9).alias('total_market_value'))
    with pytest.raises(ValueError, match='constraint inputs changed'):
        prepare_constraints(**kwargs, resume=True)



def test_constraint_cannot_reintroduce_delisted_written_off_holding():
    source = scenario()
    source['config']['portfolio']['delisted_holding_recovery'] = 0.
    source['instruments'] = source['instruments'].with_columns(pl.lit(DAYS[1]).alias('delist_date'))
    source['targets'] = source['targets'].filter(pl.col('execution_date') <= DAYS[2])
    def retain(batch, state):
        return batch.with_columns(pl.lit(1.).alias('weight')), {
            'as_of': str(batch['as_of'][0]), 'feasible': True, 'applied': False}
    account = {}
    result = replay(**source,sessions=DAYS[:3],name='probe',validate_once=True,
        account_state=account,target_constraints=retain)
    assert result[0]['delisting_writeoff'].sum() > 0
    assert not account['holdings']
    assert not result[1].filter(pl.col('date') == DAYS[2]).height
