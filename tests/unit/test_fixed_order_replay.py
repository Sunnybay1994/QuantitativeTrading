import datetime as dt

import polars as pl
import pytest

from quant.backtest import DailyMarketState, simulate_daily_targets
from tests.unit.test_daily_simulator import (
    SESSION, STOCK, _bar, _calendar, _empty_targets, _etf_costs, _initial_position,
    _instruments, _stock_costs,
)


def run_order(side='BUY', quantity=100, cash=10000.0, opening=10.0, position=None,
              state=None, orders=None):
    if orders is None:
        orders = pl.DataFrame([{'as_of': SESSION-dt.timedelta(days=3), 'execution_date': SESSION,
                               'symbol': STOCK, 'side': side, 'quantity': quantity}])
    return simulate_daily_targets(calendar=_calendar(SESSION), bars=_bar(open_price=opening),
        instruments=_instruments(), scheduled_targets=_empty_targets(), scheduled_orders=orders,
        initial_cash=cash, initial_positions=position, market_states={(SESSION, STOCK): state or DailyMarketState()},
        strategy='fixture', etf_costs=_etf_costs(), stock_costs=_stock_costs())


def test_fixed_shares_do_not_resize_when_open_price_changes():
    low, high = run_order(opening=8.0), run_order(opening=12.0)
    assert low.trades['quantity'].to_list() == high.trades['quantity'].to_list() == [100]
    assert high.nav['cash'][0] < low.nav['cash'][0]


def test_gap_up_caps_cash_and_records_the_unfilled_shares():
    result = run_order(quantity=1000, cash=5500.0, opening=10.0)
    assert result.trades['quantity'].to_list() == [500]
    row = result.rejections.row(0, named=True)
    assert row['reason'] == 'CASH_CONSTRAINT'
    assert row['requested_quantity'] == 1000 and row['rejected_quantity'] == 500
    assert result.nav['cash'][0] >= 0


@pytest.mark.parametrize('state,reason', [
    (DailyMarketState(suspended=True), 'SUSPENDED'),
    (DailyMarketState(at_upper_limit=True), 'BUY_AT_UPPER_LIMIT')])
def test_actual_execution_status_blocks_even_preapproved_orders(state, reason):
    result = run_order(state=state)
    assert result.trades.is_empty() and result.rejections['reason'].to_list() == [reason]


def test_oversell_and_lot_constraints_preserve_holdings():
    position = _initial_position(quantity=150, settled_quantity=150)
    over = run_order(side='SELL', quantity=200, position=position)
    assert over.trades.is_empty() and over.rejections['reason'].to_list() == ['INSUFFICIENT_SELLABLE']
    odd = run_order(side='SELL', quantity=50, position=position)
    assert odd.trades.is_empty() and odd.rejections['reason'].to_list() == ['LOT_CONSTRAINT']
    full = run_order(side='SELL', quantity=150, position=position)
    assert full.trades['quantity'].to_list() == [150]


def test_restricted_shares_rejected_by_same_t_plus_one_rule():
    result = run_order(side='SELL', quantity=100, position=_initial_position(quantity=100, settled_quantity=0))
    assert result.trades.is_empty() and result.rejections['reason'].to_list() == ['T_PLUS_ONE']


def test_duplicate_and_future_orders_fail_before_execution():
    orders = pl.DataFrame([{'as_of': SESSION, 'execution_date': SESSION,
                           'symbol': STOCK, 'side': 'BUY', 'quantity': 100}])
    with pytest.raises(ValueError, match='date'):
        run_order(orders=orders)
    orders = orders.with_columns(pl.lit(SESSION-dt.timedelta(days=3)).alias('as_of'))
    with pytest.raises(ValueError, match='one fixed'):
        run_order(orders=pl.concat([orders, orders]))


def test_manual_decision_and_later_replay_share_the_same_quantities():
    from quant.execution.manual_orders import prepare_manual_orders
    from quant.research.run_manual_order_replay import replay_orders
    from tests.unit.test_manual_orders import case

    args = case()
    args['state']['nav'] = [{'date': args['state']['date'], 'unit_nav': 0.9}]
    _, approved, _ = prepare_manual_orders(**args)
    args['config']['paper']['initial_cash'] = args['state']['valuation']['equity']
    closing, result = replay_orders(state=args['state'], orders=approved,
        execution_date=args['next_session'], inputs=args['inputs'], config=args['config'])
    assert result.trades.select('symbol', 'side', 'quantity').equals(approved.select('symbol', 'side', 'quantity'))
    assert len(closing['nav']) == 1
    assert closing['cash'] == pytest.approx(args['state']['cash']-result.trades['notional'].sum()-result.trades['fee'].sum())
    args['config']['paper']['sell_only'] = True
    _, result = replay_orders(state=args['state'], orders=approved,
        execution_date=args['next_session'], inputs=args['inputs'], config=args['config'])
    assert result.trades.is_empty()
    args['config']['paper']['enabled'] = False
    _, result = replay_orders(state=args['state'], orders=approved,
        execution_date=args['next_session'], inputs=args['inputs'], config=args['config'])
    assert result.trades.is_empty()


def test_cash_partial_schema_rejects_overcount_and_wrong_side():
    from quant.domain import BacktestRejectionSchema

    row = run_order(quantity=1000, cash=5500.0).rejections
    for change in (pl.lit(1001).alias('rejected_quantity'), pl.lit('SELL').alias('side')):
        with pytest.raises(Exception):
            BacktestRejectionSchema.validate(row.with_columns(change))
