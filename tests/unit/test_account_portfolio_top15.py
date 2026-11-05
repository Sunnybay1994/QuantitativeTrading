import datetime as dt
from pathlib import Path
import tomllib

import polars as pl
import pytest

from quant.backtest.daily_simulator import simulate_daily_targets
from quant.backtest.rules import DailyMarketState
from quant.execution.preposted_book import PrepostedBook
from quant.portfolio.account_portfolio_top15 import Top15Allocation,joint_orders
from quant.portfolio.top15_limit import targets
from tests.unit.test_daily_simulator import (SESSION,STOCK,ETF,_calendar,_stock_and_etf_instruments,
    _stock_and_etf_bars,_target,_stock_costs,_etf_costs)


def setup(day):
    spec=tomllib.loads(Path('configs/research/account_portfolio_top15_v1.toml').read_text(encoding='utf-8'))
    allocator=Top15Allocation(variant='fixed_40_30_30',spec=spec,
        returns=pl.DataFrame(schema={'date':pl.Date}),etf_prices=None)
    symbols=[f'{600000+i}.SH' for i in range(15)]
    scores=pl.DataFrame({'trade_date':[day]*15,'symbol':symbols,'prediction':[float(15-i) for i in range(15)]})
    closes={s:10. for s in symbols}
    closes.update({'512890.SH':1.,'511010.SH':100.})
    state={'date':str(day),'cash':300000.,'holdings':{},'nav':[{'equity':300000.}]}
    return allocator,scores,closes,state


def test_top15_lot_filter_and_original_orders_use_assigned_sleeve_not_whole_account():
    allocator,scores,closes,state=setup(dt.date(2018,12,28))
    closes[scores['symbol'][0]]=60. # One lot fits standalone 300k, but not the 120k sleeve.
    standalone,selected=targets(scores=scores,previous=[],closes=closes,equity=300000.,execution_date=SESSION)
    assert scores['symbol'][0] in selected
    stock,selected,etf,info=allocator.plan(scores=scores,previous=[],closes=closes,state=state,execution_date=SESSION)
    assert scores['symbol'][0] not in selected
    assert info['stock_equity_before_allocation']==120000. and allocator.reserved==90000.
    assert etf.select('symbol','quantity').row(0)==('511010.SH',900)
    book=PrepostedBook()
    book.replace(signal=scores['trade_date'][0],targets=stock,holdings={},
        equity=info['stock_equity_before_allocation'],closes=closes,offset=.01)
    assert all(o['original_quantity']*closes[o['symbol']]<=120000*.08 for o in book.orders)
    assert state['cash']==300000. and not state['holdings']


def test_nonquarter_preserves_etf_quantities_and_sizes_residual_stock_cash():
    allocator,scores,closes,state=setup(dt.date(2020,2,28))
    allocator.initialized=True
    state.update(cash=40000.,holdings={'512890.SH':{'quantity':90000,'mark_price':1.},
        '511010.SH':{'quantity':1000,'mark_price':100.},'600000.SH':{'quantity':7000,'mark_price':10.}})
    _,_,orders,info=allocator.plan(scores=scores,previous=['600000.SH'],closes=closes,state=state,execution_date=SESSION)
    assert orders.is_empty() and not info['quarterly_allocation']
    assert info['stock_equity_before_allocation']==110000.


def combined(stock_limit):
    schema={'as_of':pl.String,'execution_date':pl.String,'symbol':pl.String,'side':pl.String,'quantity':pl.Int64}
    stock=pl.from_dicts([dict(as_of='2026-01-02',execution_date=str(SESSION),symbol=STOCK,side='BUY',quantity=100)],schema=schema)
    etf=stock.with_columns(pl.lit(ETF).alias('symbol'))
    orders,limits=joint_orders(stock,{(STOCK,'BUY'):stock_limit},etf)
    orders=orders.with_columns(pl.col('as_of').str.to_date(),pl.col('execution_date').str.to_date())
    return simulate_daily_targets(calendar=_calendar(SESSION),bars=_stock_and_etf_bars(SESSION),
        scheduled_targets=_target(0.).head(0),scheduled_orders=orders,
        instruments=_stock_and_etf_instruments(),market_states={(SESSION,s):DailyMarketState() for s in (STOCK,ETF)},initial_cash=1100.,
        etf_costs=_etf_costs(),stock_costs=_stock_costs(),strategy='m2-u1',preposted_limits=limits)


def test_joint_matcher_keeps_unfilled_stock_cash_available_and_etf_at_open():
    result=combined(9.)
    assert result.trades['symbol'].to_list()==[ETF]
    assert result.trades['price'].item()==4.
    assert result.nav['cash'].item()>=0
    assert result.rejections.filter(pl.col('symbol')==STOCK)['reason'].to_list()==['LIMIT_NOT_REACHED']


def test_joint_matcher_enforces_shared_cash_instead_of_funding_both_sleeves():
    result=combined(10.1)
    assert result.nav['cash'].item()>=0
    assert result.trades['notional'].sum()+result.trades['fee'].sum()<=1100.+1e-8
    assert result.trades.height<2 # Both 100-share buys would require at least 1400 CNY.
