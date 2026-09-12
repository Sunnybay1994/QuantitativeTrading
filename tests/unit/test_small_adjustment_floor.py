import copy
import datetime as dt

import polars as pl
import pytest

from quant.portfolio.turnover_budget import small_adjustment_permissions
from quant.research.classic_monthly_baseline import replay
from tests.unit.test_batched_daily_replay import cash_inputs, replay_inputs
from tests.unit.test_paper_ledger import D1, D2, D3


def test_partial_buys_sells_and_new_names_block_but_zero_exits_and_boundary_do_not():
    day = dt.date(2026, 1, 30)
    state = {'date': str(day), 'nav': [{'equity': 100000.}], 'holdings': {
        s: {'quantity': 1000, 'mark_price': 10.} for s in ('buy', 'sell', 'exit')}}
    targets = pl.DataFrame({'as_of': [day]*5, 'symbol': ['buy', 'sell', 'exit', 'new', 'boundary'],
        'weight': [.14, .06, 0., .04, .05]})
    saved = copy.deepcopy(state)
    assert small_adjustment_permissions(targets, state, floor=5000.) == {
        'buy': (False, False), 'sell': (False, False), 'new': (False, False)}
    assert state == saved
    state['date'] = '2026-01-29'
    with pytest.raises(ValueError, match='signal-close'):
        small_adjustment_permissions(targets, state, floor=5000.)


def test_replay_blocks_new_position_before_execution_and_lock_expires():
    initial = cash_inputs()
    state = {}
    replay(**{**initial, 'sessions': [D1]}, account_state=state, validate_once=True)
    kwargs = replay_inputs()
    kwargs['dividends'] = kwargs['dividends'].clear()
    kwargs['targets'] = kwargs['targets'].filter(pl.col('execution_date') == D2).with_columns(pl.lit(1.).alias('weight'))
    _, trades, _ = replay(**{**kwargs, 'sessions': [D2]}, account_state=state,
        small_adjustment_floor=5000., validate_once=True)
    assert not state['holdings'] and trades.is_empty()
    kwargs['targets'] = kwargs['targets'].with_columns(pl.lit(D2).alias('as_of'), pl.lit(D3).alias('execution_date'))
    _, trades, _ = replay(**{**kwargs, 'sessions': [D3]}, account_state=state, validate_once=True)
    assert state['holdings'] and trades.height == 1


def test_zero_target_exit_is_not_blocked_even_below_floor():
    kwargs = replay_inputs()
    kwargs['dividends'] = kwargs['dividends'].clear()
    state = {}
    replay(**{**kwargs, 'sessions': [D1], 'targets': kwargs['targets'].head(1)},
        account_state=state, validate_once=True)
    targets = kwargs['targets'].filter(pl.col('execution_date') == D2).with_columns(pl.lit(0.).alias('weight'))
    _, trades, _ = replay(**{**kwargs, 'sessions': [D2], 'targets': targets}, account_state=state,
        small_adjustment_floor=5000., validate_once=True)
    assert not state['holdings'] and trades.height == 1


def test_partial_reduction_uses_signal_mark_not_next_open():
    kwargs = replay_inputs()
    kwargs['dividends'] = kwargs['dividends'].clear()
    state = {}
    replay(**{**kwargs, 'sessions': [D1], 'targets': kwargs['targets'].head(1)},
        account_state=state, validate_once=True)
    quantity = next(iter(state['holdings'].values()))['quantity']
    targets = kwargs['targets'].filter(pl.col('execution_date') == D2).with_columns(pl.lit(.5).alias('weight'))
    _, trades, _ = replay(**{**kwargs, 'sessions': [D2], 'targets': targets}, account_state=state,
        small_adjustment_floor=5000., validate_once=True)
    assert trades.is_empty()
    assert next(iter(state['holdings'].values()))['quantity'] == quantity


def test_execution_improvement_requires_every_frozen_condition():
    from quant.research.run_turnover_budget import assess_small_adjustments
    policy = {'minimum_median_trade_day_fills_reduction': .25, 'sharpe_not_lower_costs': [1., 2.],
              'max_drawdown_not_worse_costs': [1., 2.], 'retrospective_sensitivity_only': 6.5}
    rows = [{'variant': v, 'cost_multiplier': c, 'sharpe': 1., 'max_drawdown': -.2,
        'annualized_one_way_turnover': 6.3} for v in ('control', 'budgeted') for c in (1., 2.)]
    result = {'rows': rows, 'assessments': {'budgeted': {'checks': {'turnover': False, 'stress': True}}}}
    diagnostics = {'active_results': [{'variant': v, 'cost_multiplier': 1., 'median_fills_per_trade_day': n,
        'mean_active_positions': 100.} for v, n in [('control', 100), ('budgeted', 75)]]}
    passed = assess_small_adjustments(result, diagnostics, policy)
    assert passed['promote_execution_rule']
    assert passed['turnover_6_5_retrospective_only']['all_pass']
    assert not result['assessments']['budgeted']['checks']['turnover']
    rows[-1]['sharpe'] = .99
    assert not assess_small_adjustments(result, diagnostics, policy)['promote_execution_rule']
