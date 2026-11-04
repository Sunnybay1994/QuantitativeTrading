"""R3 order-time invariants; collected by the ordinary non-slow suite."""
import datetime as dt

import polars as pl
import pytest

from quant.backtest.daily_simulator import simulate_daily_targets
from quant.backtest.rules import DailyMarketState
from tests.unit.test_daily_simulator import (
    SESSION, STOCK, _calendar, _instruments, _bar, _target, _stock_costs, _etf_costs,
)


def simulate(bars, **kwargs):
    return simulate_daily_targets(calendar=_calendar(SESSION),bars=bars,
        scheduled_targets=_target(1.),instruments=_instruments(),
        market_states={(SESSION,STOCK):DailyMarketState()},initial_cash=10000.,
        stock_costs=_stock_costs(),etf_costs=_etf_costs(),strategy='m2-u1',**kwargs)


def test_open_fills_are_invariant_to_later_high_low_and_close():
    first=simulate(_bar(open_price=10.,close_price=10.))
    second=simulate(_bar(open_price=10.,close_price=11.).with_columns(
        pl.lit(100.).alias('high'),pl.lit(1.).alias('low')))
    assert first.trades.equals(second.trades)
    assert first.nav['cash'].equals(second.nav['cash'])
    assert not first.nav['equity'].equals(second.nav['equity'])


def test_one_symbol_session_cannot_spend_the_same_liquidity_twice():
    args={'execution_notional_caps':{STOCK:2500.}}
    result=simulate(_bar(open_price=10.,close_price=10.),**args)
    assert result.trades['notional'].sum()<=2500.
    assert result.trades['quantity'].sum()==200
    orders=pl.DataFrame({'as_of':[SESSION-dt.timedelta(days=1)]*2,
        'execution_date':[SESSION]*2,'symbol':[STOCK]*2,'side':['BUY','BUY'],'quantity':[200,200]})
    with pytest.raises(ValueError,match='one fixed share order per symbol and session'):
        simulate(_bar(open_price=10.,close_price=10.),scheduled_orders=orders,**args)


def test_unfilled_preposted_buy_keeps_cash_and_charges_no_cost():
    result=simulate(_bar(open_price=12.,close_price=12.).with_columns(
        pl.lit(11.).alias('low'),pl.lit(13.).alias('high')),
        preposted_limits={(STOCK,'BUY'):10.})
    assert result.trades.is_empty()
    assert result.positions['quantity'].sum()==0
    assert result.nav['cash'].item()==10000.
    assert result.nav['cumulative_fees'].item()==0.
    assert result.rejections['reason'].to_list()==['LIMIT_NOT_REACHED']
