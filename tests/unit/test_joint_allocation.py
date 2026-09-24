import datetime as dt
import polars as pl
import pytest
from quant.portfolio.joint_allocation import allocate
from quant.portfolio.turnover_budget import budget_targets


def inputs():
    b=pl.DataFrame([dict(as_of=dt.date(2023,12,29),execution_date=dt.date(2024,1,2),symbol=s,
                        weight=1.,strategy='joint',strategy_version='1') for s in ['stock_new','etf']])
    s=dict(date='2023-12-29',nav=[{'equity':100000.}],holdings={
        'stock_old':dict(quantity=600,mark_price=100.),'etf':dict(quantity=200,mark_price=100.)})
    return b,s


def test_etf_is_not_stock_exit_and_exiting_stocks_retained():
    b,s=inputs();out,info=allocate(b,s,stock_fraction=.5,etf_symbols={'etf'})
    weights=dict(out.select('symbol','weight').iter_rows())
    assert weights['stock_old']>0 and weights['etf']>0
    assert sum(weights.values())<=1+1e-10
    assert info['budget_full_equity']==.25
    assert s['holdings']['etf']['quantity']==200


def test_pure_q10_matches_existing_budget_and_pure_etf_exits_stocks():
    b,s=inputs();s['holdings'].pop('etf')
    out,_=allocate(b,s,stock_fraction=1.,etf_symbols={'etf'})
    expected=budget_targets(b.filter(pl.col('symbol')!='etf'),s,budget=.5)
    assert out.filter(pl.col('symbol')!='etf').equals(expected.sort('symbol'))
    assert out.filter(pl.col('symbol')=='etf')['weight'][0]==0
    out,_=allocate(b,s,stock_fraction=0.,etf_symbols={'etf'})
    assert dict(out.select('symbol','weight').iter_rows())=={'etf':1.,'stock_old':0.}


def test_missing_etf_target_fails_and_cash_control_no_etf_buy():
    b,s=inputs()
    with pytest.raises(ValueError,match='ETF target missing'):
        allocate(b.filter(pl.col('symbol')!='etf'),s,stock_fraction=.5,etf_symbols={'etf'})
    out,_=allocate(b,s,stock_fraction=.5,etf_symbols={'etf'},cash_control=True)
    assert out.filter(pl.col('symbol')=='etf')['weight'][0]==0
