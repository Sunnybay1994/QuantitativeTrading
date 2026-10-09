import datetime as dt
from pathlib import Path

import numpy as np
import polars as pl
from polars.testing import assert_frame_equal
import pytest

from quant.data import factor_liquidity_comovement_inputs as source
from quant.factors.liquidity_comovement import SIGNALS


@pytest.fixture(scope='module')
def actual_bars():
    low, high = dt.date(2010,1,1), dt.date(2017,3,2)
    calendar = tuple(low+dt.timedelta(days=i) for i in range((high-low).days+1)
        if (low+dt.timedelta(days=i)).weekday()<5)
    n, t = 103, len(calendar)
    rng = np.random.default_rng(100506)
    common = rng.normal(.0001,.006,t)
    moves = rng.normal(0,.004,(n,t))+np.linspace(.7,1.3,n)[:,None]*common
    price = 10*np.exp(np.cumsum(moves,axis=1))
    amount = np.exp(16+rng.normal(0,.2,(n,t))+rng.normal(0,.3,t))
    frame = pl.DataFrame({'symbol':np.repeat([f'{i:06}.SZ' for i in range(n)],t),
        'trade_date':calendar*n,'open':price.ravel(),'close':price.ravel(),
        'high':price.ravel()*1.01,'low':price.ravel()*.99,'amount':amount.ravel(),
        'volume':amount.ravel()/price.ravel(),'adj_factor':np.ones(n*t),
        'source':['fixture']*(n*t)})
    return frame, calendar


def install(monkeypatch, frame):
    reads=[]
    def reader(**kw):
        reads.append(kw)
        assert kw['table']=='bar_1d' and kw.get('symbols') is None
        return frame.filter(pl.col('trade_date').is_between(kw['start'],kw['end']))
    monkeypatch.setattr(source,'read_stock_data',reader)
    return reads


def read(calendar, start=dt.date(2016,1,1), end=dt.date(2016,3,31), **kwargs):
    return source.read_liquidity_comovement(data_root=Path('unused'),refresh_config=Path('unused'),
        calendar=calendar,start=start,end=end,**kwargs)


def test_reader_uses_sixty_one_liquidity_months_and_year_overlap(actual_bars, monkeypatch):
    frame,calendar=actual_bars
    reads=install(monkeypatch,frame)
    signals,market,monthly=read(calendar)
    assert signals['status'].unique().to_list()==['ok']
    assert len(reads)==6
    assert reads[0]['start']==dt.date(2010,12,31)
    assert reads[-1]['start']==dt.date(2015,12,31)
    assert max(q['end'] for q in reads)==dt.date(2016,3,31)
    assert monthly['trade_date'].min()==dt.date(2011,1,31)
    assert monthly['trade_date'].n_unique()==63
    assert market.height==63
    assert signals['trade_date'].n_unique()==3
    # Independent daily formula including the preceding December close.
    stock=frame.filter((pl.col('symbol')=='000000.SZ') & pl.col('trade_date').is_between(
        dt.date(2015,12,31),dt.date(2016,1,29))).sort('trade_date')
    prices=stock['close'].to_numpy()
    expected=np.mean(np.abs(prices[1:]/prices[:-1]-1)/(stock['amount'].to_numpy()[1:]/1e6))
    row=monthly.filter((pl.col('symbol')=='000000.SZ') & (pl.col('trade_date')==dt.date(2016,1,29)))
    assert row['illiquidity'].item()==pytest.approx(expected,rel=1e-12)
    assert row['monthly_return'].item()==pytest.approx(prices[-1]/prices[0]-1,rel=1e-12)


def test_early_history_and_no_anchor_do_not_fake_warmup(actual_bars, monkeypatch):
    frame,calendar=actual_bars
    reads=install(monkeypatch,frame)
    signals,_,_=read(calendar,start=dt.date(2010,1,1),end=dt.date(2010,2,28))
    assert signals['status'].unique().to_list()==['insufficient_history']
    assert signals[SIGNALS[0]].null_count()==signals.height
    reads.clear()
    empty,_,monthly=read(calendar,start=dt.date(2016,1,4),end=dt.date(2016,1,15))
    assert empty.is_empty() and monthly.is_empty() and not reads


def test_incomplete_month_not_used_and_prefix_future_invariant(actual_bars,monkeypatch):
    frame,calendar=actual_bars
    install(monkeypatch,frame)
    complete,_,monthly=read(calendar)
    prefix,_,earlier=read(calendar,end=dt.date(2016,3,15))
    assert_frame_equal(prefix,complete.filter(pl.col('trade_date')<=dt.date(2016,2,29)))
    assert_frame_equal(earlier,monthly.filter(pl.col('trade_date')<=dt.date(2016,2,29)))
    altered=frame.with_columns(*[pl.when(pl.col('trade_date')>=dt.date(2016,3,1)).then(pl.col(n)*7)
        .otherwise(pl.col(n)).alias(n) for n in ('open','close','high','low','amount','volume')])
    install(monkeypatch,altered)
    future,_,_=read(calendar)
    assert_frame_equal(prefix,future.filter(pl.col('trade_date')<=dt.date(2016,2,29)))


def test_suspended_endpoint_and_missing_daily_grid_are_not_carried(actual_bars,monkeypatch):
    frame,calendar=actual_bars
    gap=(pl.col('symbol')=='000000.SZ') & pl.col('trade_date').is_between(dt.date(2016,1,20),dt.date(2016,1,29))
    altered=frame.filter(~gap)
    install(monkeypatch,altered)
    signals,_,monthly=read(calendar)
    target=monthly.filter((pl.col('symbol')=='000000.SZ') & (pl.col('trade_date')>=dt.date(2016,1,1)))
    assert target['illiquidity'][0] is None
    assert target['monthly_return'][:2].null_count()==2
    assert signals.filter((pl.col('symbol')=='000000.SZ') & (pl.col('trade_date')<dt.date(2016,3,1)))[SIGNALS[0]].null_count()==2


def test_threshold_is_exchange_calendar_not_received_days(actual_bars,monkeypatch):
    frame,calendar=actual_bars
    # Keep 15 observed February sessions out of 21: the threshold must remain 17.
    feb=[d for d in calendar if d.year==2016 and d.month==2]
    altered=frame.filter(~((pl.col('symbol')=='000000.SZ') & pl.col('trade_date').is_in(feb[15:])))
    install(monkeypatch,altered)
    _,_,monthly=read(calendar)
    assert monthly.filter((pl.col('symbol')=='000000.SZ') & (pl.col('trade_date')==feb[-1]))['illiquidity'].item() is None


def test_monthly_liquidity_survives_missing_last_quote_without_filling_return(actual_bars,monkeypatch):
    frame,calendar=actual_bars
    last=dt.date(2016,1,29)
    altered=frame.filter(~((pl.col('symbol')=='000000.SZ') & (pl.col('trade_date')==last)))
    install(monkeypatch,altered)
    signals,market,monthly=read(calendar)
    row=monthly.filter((pl.col('symbol')=='000000.SZ') & (pl.col('trade_date')==last))
    # 20/21 real daily returns still clear the frozen 80% threshold. A daily
    # factor cache has no quotation row on this last day; it is not the source.
    assert row['illiquidity'].item()>0
    assert row['monthly_return'].item() is None
    assert signals.filter((pl.col('symbol')=='000000.SZ') & (pl.col('trade_date')==last))[SIGNALS[0]].item() is None
    assert market.filter(pl.col('trade_date')==dt.date(2016,2,29))['reference_members'].item()==103


def test_definition_mismatch_does_not_read_data(actual_bars,monkeypatch,tmp_path):
    _,calendar=actual_bars
    path=tmp_path/'definition.toml'
    path.write_text(source.DEFINITION.read_text().replace('formation_months = 60','formation_months = 36'))
    monkeypatch.setattr(source,'read_stock_data',lambda **kw:pytest.fail('unexpected data read'))
    with pytest.raises(ValueError,match='fixed kernel'):
        read(calendar,definition=path)


def test_disagreeing_overlap_is_an_error(actual_bars,monkeypatch):
    frame,calendar=actual_bars
    calls=[]
    def reader(**kw):
        calls.append(kw)
        part=frame.filter(pl.col('trade_date').is_between(kw['start'],kw['end']))
        return part if len(calls)==1 else part.with_columns(
            pl.when(pl.col('trade_date')==kw['start']).then(pl.col('close')*1.001)
              .otherwise(pl.col('close')).alias('close'))
    monkeypatch.setattr(source,'read_stock_data',reader)
    with pytest.raises(ValueError,match='endpoints disagree'):
        read(calendar)
