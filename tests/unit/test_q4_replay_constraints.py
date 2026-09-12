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



def test_nominee_buffer_survives_daily_advance_and_account_checkpoint(tmp_path, monkeypatch):
    source, _, kwargs = setup_run(monkeypatch, tmp_path/'nominee_run')
    kwargs['settings'] = {**kwargs['settings'], 'target_constraints_config': 'nominee_fixture'}
    observed = []
    def nominate(batch, state):
        observed.append(state.get('constraint_nominees'))
        return batch, {'as_of':str(batch['as_of'][0]),'feasible':True,'applied':False,
            'nominee_symbols': ['persisted_nominee']}
    costs.run_cost_plans(**kwargs,target_constraints=nominate)
    assert observed[0] is None
    assert observed[1] == ['persisted_nominee']
    assert observed[2] is None  # The next cost scenario owns a separate account.
    checkpoint = json.loads((kwargs['output']/'raw/cost_1/2021/account.json').read_text())
    assert checkpoint['account']['constraint_nominees'] == ['persisted_nominee']
    costs.run_cost_plans(**kwargs,target_constraints=nominate,resume=True)

def test_directional_signal_sell_permission():
    from quant.research.run_multifactor_replay import signal_sell_permission
    market = pl.DataFrame({'close': [11., 9., 10., 11., 11., 10., 10.],
        'up_limit': [11., 11., 11., None, 11., 11., 8.],
        'down_limit': [9., 9., 9., 9., 9., 9., 9.],
        'traded': [True, True, True, True, False, True, True],
        'limits_known': [True, True, True, False, True, None, True]})
    assert market.select(signal_sell_permission())[:, 0].to_list() == [True, False, True, False, False, False, False]

def test_constraint_input_exception_records_signal_account(tmp_path, monkeypatch):
    _, _, kwargs = setup_run(monkeypatch, tmp_path/'run')
    kwargs['settings'] = {**kwargs['settings'], 'target_constraints_config': 'fixture'}
    def invalid_controls(batch, state):
        if batch['execution_date'][0].year == 2021:
            raise ValueError('Missing PIT industry/size for A')
        return batch, {'as_of': str(batch['as_of'][0]), 'feasible': True, 'applied': False}
    with pytest.raises(ValueError, match='Missing PIT'):
        costs.run_cost_plans(**kwargs, target_constraints=invalid_controls)
    failure = next((kwargs['output']/'raw/cost_0.5').glob('constraints_failure_2021_*.json'))
    diagnostic = json.loads(failure.read_text())['diagnostics'][-1]
    assert not diagnostic['feasible']
    assert not diagnostic['constraint_output_valid']
    assert diagnostic['as_of'] == diagnostic['account_at_signal']['date']
    assert sum(h['quantity'] for h in diagnostic['account_at_signal']['holdings'].values()) > 0
    assert diagnostic['account_at_signal']['nav']['equity'] > 0

def test_held_risk_overlay_is_snapshotted_and_only_applied_to_actual_positions(tmp_path,monkeypatch):
    import datetime as dt
    from quant.data import equal_weight_index,factor_battery_inputs,held_control_supplements
    from quant.portfolio import simple_constraints
    day=dt.date(2024,4,30)
    batch=pl.DataFrame({'as_of':[day],'execution_date':[dt.date(2024,5,6)],
        'symbol':['B'],'strategy':['probe'],'weight':[.02]})
    universe=pl.DataFrame({'trade_date':[day],'symbol':['B'],'industry_l1':['X'],
        'total_market_value':[1e9],'amount20':[1e8],'eligible':[True],
        'traded':[True],'limits_known':[True],'away_from_limits':[True],
        'close':[10.],'up_limit':[11.],'down_limit':[9.]})
    estimates=pl.DataFrame({'as_of':[day],'symbol':['A'],'industry_l1':['X'],
        'total_market_value':[2e9],'source_date':[day-dt.timedelta(days=1)],
        'staleness_days':[1],'known_at':[day],'risk_estimate':[True],
        'suspended':[True],'capital_events_verified':[True]})
    path=tmp_path/'risk.parquet'
    estimates.write_parquet(path)
    monkeypatch.setattr(factor_battery_inputs,'read_frozen_battery_universe',lambda **kw: universe)
    monkeypatch.setattr(equal_weight_index,'read_equal_weight_targets',lambda **kw:
        batch.select('as_of','symbol').with_columns(pl.lit(1.).alias('weight')))
    monkeypatch.setattr(held_control_supplements,'read_held_risk_estimates',lambda **kw: estimates,raising=False)
    observed=[]
    def capture(**kw):
        observed.append(kw['market'])
        return kw['targets'],{'feasible':True}
    monkeypatch.setattr(simple_constraints,'constrain_account_targets',capture)
    config=tmp_path/'config.toml'
    config.write_text('auto_trade=false\nmode="research_only"\nstrategy_names=["probe"]\n'
        'statistics="fixture"\nbenchmark_snapshot="fixture"\nbenchmark="all_market_equal_weight"\n'
        'enabled=true\nsell_only=false\nunknown_industry_policy="explicit_unknown_bucket"\n'
        '[limits]\nsingle_stock_weight=0.03\n[held_risk_estimate]\n'
        f'path="{path.as_posix()}"\nmaximum_staleness_days=7\n')
    output=tmp_path/'out'
    output.mkdir()
    kwargs=dict(config=config,plans={'raw':('probe',batch)},data_root=tmp_path,output=output)
    hook,_=prepare_constraints(**kwargs,resume=False)
    state={'date':str(day),'nav':[{'equity':10000.}],
        'holdings':{'A':{'quantity':10,'mark_price':10.}}}
    _,info=hook(batch,state)
    assert info['held_risk_estimates'][0]['symbol']=='A'
    assert observed[-1].filter(pl.col('symbol')=='A')['can_sell'][0] is False
    state['holdings']={}
    _,info=hook(batch,state)
    assert 'held_risk_estimates' not in info
    assert 'A' not in observed[-1]['symbol'].to_list()
    estimates=estimates.with_columns(pl.lit(False).alias('capital_events_verified'))
    with pytest.raises(ValueError,match='constraint inputs changed'):
        prepare_constraints(**kwargs,resume=True)
