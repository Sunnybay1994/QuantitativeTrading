import copy
import datetime as dt
import json

import polars as pl
import pytest

from quant.portfolio.missing_control_hold import hold_missing_controls, validate_quantity_hold
from quant.reporting.multifactor_models import apply_constraint_coverage

DAY = dt.date(2024, 5, 31)


def inputs():
    targets = pl.DataFrame({'as_of': [DAY, DAY], 'execution_date': [dt.date(2024, 6, 3)]*2,
        'symbol': ['B', 'C'], 'weight': [.5, .5], 'strategy': ['probe']*2})
    state = {'date': str(DAY), 'nav': [{'equity': 10000.}], 'holdings': {
        'H': {'quantity': 100, 'mark_price': 10.}, 'B': {'quantity': 200, 'mark_price': 10.}}}
    market = pl.DataFrame({'symbol': ['B', 'C'], 'industry_l1': ['X', 'Y'],
        'total_market_value': [1e9, 2e9]})
    benchmark = pl.DataFrame({'as_of': [DAY]*2, 'symbol': ['B', 'C'], 'weight': [.5, .5]})
    return dict(targets=targets, state=state, market=market, benchmark=benchmark,
                unknown_industry_policy='explicit_unknown_bucket')


def test_missing_holding_freezes_whole_account_without_imputation_or_state_change():
    kwargs = inputs()
    saved = copy.deepcopy(kwargs['state'])
    market = kwargs['market'].clone()
    targets, info = hold_missing_controls(**kwargs)
    assert dict(targets.select('symbol', 'weight').iter_rows()) == {'B': .2, 'H': .1}
    assert info['unmodeled_held_weight'] == .1
    assert not info['feasible'] and not info['constraints_verified']
    assert info['execution_direction_permissions'] == {'H': (False, False), 'B': (False, False)}
    assert kwargs['state'] == saved and kwargs['market'].equals(market)
    validate_quantity_hold(targets=targets, state=kwargs['state'], info=info)


@pytest.mark.parametrize('mutation', ['new_target', 'quantity_permission', 'weight'])
def test_no_trade_continuation_cannot_hide_a_trade(mutation):
    kwargs = inputs()
    targets, info = hold_missing_controls(**kwargs)
    if mutation == 'new_target':
        targets = targets.with_columns(pl.when(pl.col('symbol') == 'H')
            .then(pl.lit('C')).otherwise(pl.col('symbol')).alias('symbol'))
    elif mutation == 'quantity_permission':
        info['execution_direction_permissions']['B'] = (True, False)
    else:
        targets = targets.with_columns((pl.col('weight')/2).alias('weight'))
    with pytest.raises(ValueError, match='Unverified continuation'):
        validate_quantity_hold(targets=targets, state=kwargs['state'], info=info)


def test_missing_benchmark_is_not_a_held_only_exception():
    kwargs = inputs()
    kwargs['market'] = kwargs['market'].filter(pl.col('symbol') == 'B')
    with pytest.raises(ValueError, match='Missing benchmark controls'):
        hold_missing_controls(**kwargs)


def test_complete_holdings_resume_original_projection_path():
    kwargs = inputs()
    kwargs['market'] = pl.concat([kwargs['market'], pl.DataFrame({'symbol': ['H'],
        'industry_l1': ['X'], 'total_market_value': [3e9]})])
    assert hold_missing_controls(**kwargs) is None


def test_invalid_target_is_not_hidden_by_no_trade_policy():
    kwargs = inputs()
    kwargs['targets'] = kwargs['targets'].with_columns(pl.lit(float('nan')).alias('weight'))
    with pytest.raises(ValueError, match='valid signal-close account and targets'):
        hold_missing_controls(**kwargs)


def test_unverified_constraint_cannot_be_promoted_by_a_profitable_report(tmp_path):
    folder = tmp_path/'lightgbm_top50/cost_1/2024'
    folder.mkdir(parents=True)
    (folder/'account.json').write_text('{}')
    event = hold_missing_controls(**inputs())[1]
    (folder/'constraints.json').write_text(json.dumps([event]))
    assessment = {'conclusion': 'PAPER_CANDIDATE', 'checks': {'net_excess': True}}
    apply_constraint_coverage(assessment, run=tmp_path, variant='lightgbm_top50', costs=[1.])
    assert assessment['conclusion'] == 'REJECTED'
    assert assessment['checks']['net_excess']
    assert not assessment['checks']['portfolio_constraints_verified']
    assert assessment['constraint_coverage']['scenarios'][0]['hold_dates'] == [str(DAY)]


def test_replay_continues_valuation_but_submits_no_orders_for_explicit_hold():
    from quant.research.classic_monthly_baseline import replay
    from tests.unit.test_factor_cost_checkpoint import DAYS, SYMBOL, scenario

    source = scenario()
    source['dividends'] = source['dividends'].clear()
    state, diagnostics = {}, []
    def transform(batch, account):
        if not account['holdings']:
            return batch, {'as_of': str(batch['as_of'][0]), 'feasible': True, 'applied': False}
        day = batch['as_of'][0]
        return hold_missing_controls(targets=batch, state=account,
            market=pl.DataFrame({'symbol': ['REFERENCE'], 'industry_l1': ['X'], 'total_market_value': [1e9]}),
            benchmark=pl.DataFrame({'as_of': [day], 'symbol': ['REFERENCE'], 'weight': [1.]}),
            unknown_industry_policy='reject')
    nav, trades, _ = replay(**source, sessions=DAYS, name='probe', account_state=state,
        target_constraints=transform, constraint_diagnostics=diagnostics, validate_once=True)
    held_events = [d for d in diagnostics if d.get('action') == 'hold_actual_quantities']
    assert held_events and nav.height == len(DAYS)
    assert state['holdings'][SYMBOL]['quantity'] > 0
    assert trades.filter(pl.col('date') > DAYS[0]).is_empty()


def test_later_complete_signal_releases_quantity_hold_and_allows_original_exit():
    from quant.research.classic_monthly_baseline import replay
    from tests.unit.test_factor_cost_checkpoint import DAYS, scenario

    source = scenario()
    source['dividends'] = source['dividends'].clear()
    state, diagnostics = {}, []
    def transform(batch, account):
        if batch['execution_date'][0] != DAYS[2]:
            return batch, {'as_of': str(batch['as_of'][0]), 'feasible': True, 'applied': False}
        day = batch['as_of'][0]
        return hold_missing_controls(targets=batch, state=account,
            market=pl.DataFrame({'symbol': ['REFERENCE'], 'industry_l1': ['X'], 'total_market_value': [1e9]}),
            benchmark=pl.DataFrame({'as_of': [day], 'symbol': ['REFERENCE'], 'weight': [1.]}),
            unknown_industry_policy='reject')
    nav, trades, _ = replay(**source, sessions=DAYS, name='probe', account_state=state,
        target_constraints=transform, constraint_diagnostics=diagnostics, validate_once=True)
    assert sum(d.get('action') == 'hold_actual_quantities' for d in diagnostics) == 1
    assert trades.filter(pl.col('date') == DAYS[2]).is_empty()
    assert trades.filter(pl.col('date') == DAYS[-1]).height == 1
    assert not state['holdings'] and nav['market_value'][-1] == 0
