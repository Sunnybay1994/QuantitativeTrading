import copy

import polars as pl
import pytest

from quant.portfolio.missing_control_hold import (
    hold_missing_controls, isolate_missing_controls, validate_quantity_isolation,
)
from tests.unit.test_missing_control_hold import inputs


def test_liquid_capital_and_frozen_quantity_use_original_account():
    args = inputs()
    state = args['state']
    state['cash'] = 7000.
    before = copy.deepcopy(state)
    def project(targets, liquid, frozen, cash_buffer):
        assert frozen == ['H']
        assert liquid['nav'][-1]['equity'] == 9000.
        assert liquid['cash'] == 7000.
        assert set(liquid['holdings']) == {'B'}
        assert cash_buffer == pytest.approx(.02/.9)
        return targets.with_columns(pl.lit(.4).alias('weight')), {'feasible': True}
    targets, info = isolate_missing_controls(targets=args['targets'], state=state,
        continuation=hold_missing_controls(**args), cash_buffer=.02, project=project)
    assert dict(targets.select('symbol', 'weight').iter_rows()) == pytest.approx({'B': .36, 'C': .36, 'H': .1})
    assert info['execution_direction_permissions']['H'] == (False, False)
    assert not info['constraints_verified'] and not info['feasible']
    assert info['full_book_size_bound'] is None
    assert state == before
    validate_quantity_isolation(targets=targets, state=state, info=info)
    info['execution_direction_permissions']['H'] = (False, True)
    with pytest.raises(ValueError, match='quantity'):
        validate_quantity_isolation(targets=targets, state=state, info=info)


@pytest.mark.parametrize('failure', ['infeasible', 'exception', 'frozen_reintroduced'])
def test_liquid_failure_returns_original_whole_account_hold(failure):
    args = inputs()
    def project(targets, state, frozen, cash_buffer):
        if failure == 'exception':
            raise ValueError('missing liquid controls')
        if failure == 'frozen_reintroduced':
            targets = targets.with_columns(pl.lit('H').alias('symbol'))
        return targets, {'feasible': failure != 'infeasible'}
    expected, _ = hold_missing_controls(**args)
    targets, info = isolate_missing_controls(targets=args['targets'], state=args['state'],
        continuation=hold_missing_controls(**args), cash_buffer=.02, project=project)
    assert targets.equals(expected)
    assert info['action'] == 'hold_actual_quantities'
    assert info['isolation_failure']
    assert all(pair == (False, False) for pair in info['execution_direction_permissions'].values())



def test_real_projection_accounts_for_frozen_value_and_full_cash_floor():
    from quant.portfolio.simple_constraints import RelativeConstraintLimits, constrain_account_targets
    args = inputs()
    day = args['targets']['as_of'][0]
    args['state'].update(cash=7000.)
    args['state']['nav'][-1].update(date=str(day), cash=7000.)
    market = args['market'].with_columns(pl.lit(day).alias('as_of'), pl.lit(day).alias('known_at'),
        pl.lit(1e8).alias('adv20'), pl.lit(True).alias('can_buy'), pl.lit(True).alias('can_sell'))
    def project(targets, state, frozen, cash_buffer):
        return constrain_account_targets(targets=targets, state=state, market=market,
            benchmark=args['benchmark'], limits=RelativeConstraintLimits(cash_buffer=cash_buffer,
                single_stock_weight=.6, industry_active_band=.5, size_active_band=10.),
            unknown_industry_policy='explicit_unknown_bucket', diagnostic_only=True)
    targets, info = isolate_missing_controls(targets=args['targets'], state=args['state'],
        continuation=hold_missing_controls(**args), cash_buffer=.02, project=project)
    assert info['action'] == 'isolate_actual_quantities', info
    assert info['liquid_constraint_diagnostics']['account_equity'] == 9000.
    assert targets['weight'].sum() <= .98+1e-8


def test_isolation_executes_liquid_orders_and_preserves_frozen_shares_across_year():
    from quant.backtest import DailyMarketState
    from quant.research.classic_monthly_baseline import replay
    from tests.unit.test_factor_cost_checkpoint import DAYS, SYMBOL, scenario
    source = scenario()
    other = '510500.SH'
    source['dividends'] = source['dividends'].clear()
    source['config']['portfolio']['initial_cash'] = 10000.
    for name in ('bars', 'instruments'):
        source[name] = pl.concat([source[name], source[name].with_columns(pl.lit(other).alias('symbol'))])
    source['market_states'].update({(day, other): DailyMarketState() for day in DAYS})
    original = source['targets'].with_columns(pl.col('weight')*.5)
    source['targets'] = pl.concat([original, original.with_columns(
        pl.lit(other).alias('symbol'), pl.lit(0.).alias('weight'))]).sort('execution_date', 'symbol')
    state, diagnostics = {}, []
    def transform(batch, account):
        if not account['holdings']:
            return batch, {'feasible': True, 'applied': False}
        day = batch['as_of'][0]
        continuation = hold_missing_controls(targets=batch, state=account,
            market=pl.DataFrame({'symbol': [other], 'industry_l1': ['X'], 'total_market_value': [1e9]}),
            benchmark=pl.DataFrame({'as_of': [day], 'symbol': [other], 'weight': [1.]}),
            unknown_industry_policy='reject')
        return isolate_missing_controls(targets=batch, state=account, continuation=continuation,
            cash_buffer=.02, project=lambda targets, liquid, frozen, reserve: (
                targets.with_columns(pl.lit(.8).alias('weight')), {'feasible': True}))
    for days in (DAYS[:3], DAYS[3:]):
        replay(**source, sessions=days, name='probe', account_state=state,
            target_constraints=transform, constraint_diagnostics=diagnostics, validate_once=True)
        assert state['holdings'][SYMBOL]['quantity'] == 500
        assert state['holdings'][other]['quantity'] == 400
    assert len(state['nav']) == len(DAYS)
    assert sum(d.get('action') == 'isolate_actual_quantities' for d in diagnostics) == 2


def test_isolated_full_portfolio_remains_rejected_in_report(tmp_path):
    import json
    from quant.reporting.multifactor_models import apply_constraint_coverage
    folder = tmp_path/'lightgbm_top50/cost_1/2024'
    folder.mkdir(parents=True)
    (folder/'account.json').write_text('{}')
    (folder/'constraints.json').write_text(json.dumps([{
        'as_of': '2024-05-31', 'feasible': False, 'constraints_verified': False,
        'action': 'isolate_actual_quantities', 'unmodeled_held_weight': .003,
        'liquid_constraints_verified': True}]))
    assessment = {'checks': {}, 'conclusion': 'PAPER_CANDIDATE'}
    apply_constraint_coverage(assessment, run=tmp_path, variant='lightgbm_top50', costs=[1.])
    assert assessment['conclusion'] == 'REJECTED'
    assert not assessment['checks']['portfolio_constraints_verified']
    assert assessment['constraint_coverage']['scenarios'][0]['isolated_dates'] == ['2024-05-31']
