import polars as pl
import pytest

from quant.backtest.daily_simulator import simulate_daily_targets
from quant.backtest.rules import DailyMarketState
from tests.unit.test_daily_simulator import (
    SESSION,STOCK,_calendar,_instruments,_bar,_target,_initial_position,_stock_costs,_etf_costs,_stock_costs_scaled,
)


def run(side, opening, low, high, limit, *, costs=None, state=None):
    return simulate_daily_targets(calendar=_calendar(SESSION),
        bars=_bar(open_price=opening,close_price=opening).with_columns(pl.lit(low).alias('low'),pl.lit(high).alias('high')),
        scheduled_targets=_target(1. if side=='BUY' else 0.),instruments=_instruments(),
        market_states={(SESSION,STOCK):state or DailyMarketState()},initial_cash=10000.,
        initial_positions=_initial_position(quantity=100,settled_quantity=100) if side=='SELL' else None,
        target_share_deltas={STOCK:100 if side=='BUY' else -100},
        etf_costs=_etf_costs(),stock_costs=costs or _stock_costs(),strategy='m2-u1',
        preposted_limits={(STOCK,side):limit})


@pytest.mark.parametrize('side,opening,low,high,limit,price',[
    ('BUY',9.,8.,12.,10.,9.),('BUY',11.,9.,12.,10.,10.),
    ('SELL',11.,8.,12.,10.,11.),('SELL',9.,8.,12.,10.,10.)])
def test_symmetric_open_or_limit_matching(side,opening,low,high,limit,price):
    result=run(side,opening,low,high,limit)
    assert result.trades['quantity'].to_list()==[100]
    assert result.trades['price'].item()==price


@pytest.mark.parametrize('side,opening,low,high,limit',[
    ('BUY',12.,11.,13.,10.),('SELL',8.,7.,9.,10.)])
def test_unreached_limit_leaves_cash_and_shares_without_fees(side,opening,low,high,limit):
    result=run(side,opening,low,high,limit,costs=_stock_costs_scaled(2.))
    assert result.trades.is_empty()
    assert result.nav['cash'].item()==10000.
    assert result.nav['cumulative_fees'].item()==0.
    assert result.positions['quantity'].sum()==(100 if side=='SELL' else 0)
    assert result.rejections['reason'].to_list()==['LIMIT_NOT_REACHED']


def test_open_fill_does_not_look_at_later_high_low_or_close():
    first=run('BUY',9.,8.,12.,10.)
    second=run('BUY',9.,1.,90.,10.)
    assert first.trades.equals(second.trades)


def test_limit_quote_then_original_cost_friction_charged_once():
    result=run('BUY',11.,9.,12.,10.,costs=_stock_costs_scaled(1.))
    trade=result.trades.row(0,named=True)
    quoted=trade['price']-trade['slippage_cost']/trade['quantity']
    assert quoted==pytest.approx(10.)
    assert trade['price']==pytest.approx(10.01)
    assert result.nav['cash'].item()==pytest.approx(10000-trade['notional']-trade['fee'])


def test_limit_cannot_bypass_suspension():
    result=run('BUY',9.,8.,12.,10.,state=DailyMarketState(suspended=True))
    assert result.trades.is_empty()
    assert result.rejections['reason'].to_list()==['SUSPENDED']
