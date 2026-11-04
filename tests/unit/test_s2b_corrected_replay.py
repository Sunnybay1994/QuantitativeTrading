import datetime as dt

import polars as pl
import pytest

from quant.research.s2b_corrected_replay import total_return,dense_targets
from quant.research.s2b_price_audit import reconstruct


def test_split_and_cash_distribution_preserve_value_without_raw_price_shocks():
    dates=[dt.date(2020,1,i) for i in (2,3,6,7)]
    daily=pl.DataFrame({'trade_date':dates,'close':[10.,2.5,2.5,2.4]})
    panel=total_return(daily,sessions=dates,splits={dates[1]:4.},
        dividends={dates[-1]:.1},nontrading=set())
    assert panel['close'].to_list()==pytest.approx([1.]*4)
    missing=daily.filter(pl.col('trade_date')!=dates[2])
    with pytest.raises(ValueError,match='Unverified quote gap'):
        total_return(missing,sessions=dates,splits={dates[1]:4.},dividends={},nontrading=set())
    valued=total_return(missing,sessions=dates,splits={dates[1]:4.},dividends={},nontrading={dates[2]})
    assert valued.filter(pl.col('trade_date')==dates[2])['tradable'].item() is False


def test_monthly_replacement_zeros_exited_names_instead_of_accumulating_leverage():
    d1,d2,d3=dt.date(2020,1,2),dt.date(2020,1,3),dt.date(2020,2,3)
    weights=pl.DataFrame({'as_of':[d1,d2],'execution_date':[d2,d3],
        'symbol':['A','B'],'weight':[1.,1.]})
    prices=pl.DataFrame({'symbol':['A']*3+['B']*3,'trade_date':[d1,d2,d3]*2,
        'close':[1.,1.1,1.2,1.,1.1,1.2]})
    _,old=reconstruct(prices,weights,cost=0.)
    positions,fixed=reconstruct(prices,dense_targets(weights,['A','B']),cost=0.,chronological=True)
    assert old['exposure'].max()==2.
    assert fixed['exposure'].max()==1.
    assert positions.filter((pl.col('symbol')=='A')&(pl.col('trade_date')==d3))['weight'].item()==0.
    _,higher=reconstruct(prices,dense_targets(weights,['A','B']),cost=.01,chronological=True)
    assert fixed['trade_date'].is_sorted() and fixed['trade_date'].equals(higher['trade_date'])
    assert (higher['unit_nav']<=fixed['unit_nav']).all()
