import datetime as dt

import polars as pl
import pytest

from quant.backtest.account_reconciliation import check_transition, validate_nav
from quant.backtest.daily_account import advance
from quant.backtest.rules import DailyMarketState
from tests.unit.test_daily_simulator import (
    ETF, STOCK, _calendar, _stock_and_etf_bars, _stock_and_etf_instruments, _stock_costs, _etf_costs,
)

DAY=dt.date(2021,10,22)


def calendar(day):
    return pl.concat([_calendar(DAY-dt.timedelta(days=1)),_calendar(day)]).unique(['market','date'])


def case(*,adjust=None,ratio=1.,action_type=None):
    state={'date':'2021-10-21','cash':1000.,'holdings':{ETF:{'quantity':1000,'mark_price':1.639}},
           'receivables':[],'pending':[],'nav':[{'date':'2021-10-21','equity':2639.}]}
    row=dict(symbol=ETF,ann_date=dt.date(2021,10,18),record_date=dt.date(2021,10,21),ex_date=DAY,
             pay_date=DAY,share_list_date=dt.date(2021,10,25),div_cash=0.,share_ratio=ratio)
    event=pl.from_dicts([row]).with_columns(pl.lit(adjust,dtype=pl.Boolean).alias('adjust_share_price'),
                                          pl.lit(action_type,dtype=pl.String).alias('action_type'))
    config={'paper':{'name':'split-test','auto_trade':False,'initial_cash':2639.},
            'costs':{'etf':_etf_costs().__dict__,'a_share':_stock_costs().__dict__}}
    return state,event,config


def test_mixed_stock_etf_null_flag_keeps_split_book_value_and_reopening_loss():
    state,event,config=case()
    stock=event.with_columns(pl.lit(STOCK).alias('symbol'),pl.lit(True).alias('adjust_share_price'))
    event=pl.concat([event.drop('adjust_share_price'),stock],how='diagonal_relaxed')
    assert event.filter(pl.col('symbol')==ETF)['adjust_share_price'].item() is None
    after,_=advance(date=DAY,state=state,bars=_stock_and_etf_bars(DAY).head(0),calendar=calendar(DAY),
        instruments=_stock_and_etf_instruments(),market_states={(DAY,ETF):DailyMarketState(suspended=True)},
        dividends=event,config=config)
    assert after['holdings'][ETF]['quantity']==2000
    assert after['holdings'][ETF]['mark_price']==pytest.approx(.8195)
    assert after['nav'][-1]['equity']==pytest.approx(2639.)
    assert after['nav'][-1]['reconciliation_unexplained_return']==pytest.approx(0.)
    reopening=dt.date(2021,10,25)
    bars=_stock_and_etf_bars(reopening).filter(pl.col('symbol')==ETF).with_columns(
        pl.lit(.87).alias('open'),pl.lit(.87).alias('high'),pl.lit(.79).alias('low'),pl.lit(.801).alias('close'))
    end,_=advance(date=reopening,state=after,bars=bars,calendar=calendar(reopening),
        instruments=_stock_and_etf_instruments(),market_states={(reopening,ETF):DailyMarketState()},
        dividends=event,config=config)
    assert end['nav'][-1]['equity']==pytest.approx(2602.)


def test_independent_guard_rejects_old_unadjusted_split_mark():
    state,event,_=case()
    empty=pl.DataFrame(schema={'symbol':pl.String,'trade_date':pl.Date,'close':pl.Float64})
    fills=pl.DataFrame(schema={'symbol':pl.String,'side':pl.String,'quantity':pl.Int64,'price':pl.Float64,'fee':pl.Float64})
    with pytest.raises(ValueError,match='UNEXPLAINED_NAV_JUMP'):
        check_transition(date=DAY,previous=state,actual_equity=4278.,bars=empty,dividends=event,trades=fills)


def test_explicit_uncompensated_issue_and_economic_consolidation_remain_distinct():
    state,event,config=case(adjust=False)
    after,_=advance(date=DAY,state=state,bars=_stock_and_etf_bars(DAY).head(0),calendar=calendar(DAY),
        instruments=_stock_and_etf_instruments(),market_states={(DAY,ETF):DailyMarketState(suspended=True)},
        dividends=event,config=config)
    assert after['holdings'][ETF]['mark_price']==1.639
    assert after['nav'][-1]['equity']==pytest.approx(4278.)
    state,event,config=case(adjust=True,ratio=-.5,action_type='SHARE_CONSOLIDATION')
    state['share_reduction_entitlements']={f'{ETF}|{DAY}':1000}
    after,_=advance(date=DAY,state=state,bars=_stock_and_etf_bars(DAY).head(0),calendar=calendar(DAY),
        instruments=_stock_and_etf_instruments(),market_states={(DAY,ETF):DailyMarketState(suspended=True)},
        dividends=event,config=config)
    assert after['holdings'][ETF]['quantity']==500
    assert after['holdings'][ETF]['mark_price']==pytest.approx(3.278)
    assert after['nav'][-1]['equity']==pytest.approx(2639.)


def test_registry_recomputes_residual_instead_of_trusting_saved_pass_label():
    nav=pl.DataFrame({'equity':[130.],'reconciliation_expected_equity':[100.],
        'reconciliation_previous_equity':[100.],'reconciliation_unexplained_return':[0.]})
    with pytest.raises(ValueError,match='UNEXPLAINED_NAV_JUMP'):
        validate_nav(nav)


def test_direct_registry_append_cannot_bypass_account_ledger_guard(tmp_path):
    import json
    from quant.reporting.experiment_registry import append_records
    run=tmp_path/'old_account';run.mkdir()
    pl.DataFrame({'date':[DAY],'equity':[130.]}).write_parquet(run/'nav.parquet')
    (run/'summary.json').write_text(json.dumps({'completed':[{'path':str(run)}]}))
    registry=tmp_path/'registry.parquet'
    with pytest.raises(ValueError,match='Missing independent account reconciliation'):
        append_records([{'experiment_id':'account_portfolio_v1','run_path':str(run),'variant':'fixed'}],registry)
    assert not registry.exists()
