import copy
import datetime as dt
from pathlib import Path
import statistics
import tomllib

import polars as pl
from polars.testing import assert_frame_equal
import pytest

from quant.factors.alpha101_055 import compute_alpha101_055
from quant.research.monthly_alpha101_055 import validate_alpha101_055

DATES = tuple(dt.date(2024, 1, 1)+dt.timedelta(days=i) for i in range(40))


def sample():
    return pl.DataFrame([dict(symbol=f'60000{j}.SH',trade_date=day,
        high=15.+(i%5),low=7.+(i%3)/4,close=8.+((i*(j+2)+j)%11)/2,
        adj_factor=1.,volume=100.+((i*(j+3)+j*2)%13)*10)
        for j in range(5) for i,day in enumerate(DATES)])


def rank(value, values):
    if len(values)==1:
        return .5
    return (sum(x<value for x in values)+(sum(x==value for x in values)-1)/2)/(len(values)-1)


def test_scalar_cross_section_then_time_correlation():
    bars=sample()
    rows={(r['symbol'],r['trade_date']):r for r in bars.to_dicts()}
    symbols=sorted(bars['symbol'].unique())
    pos={}
    volumes={}
    for i,day in enumerate(DATES):
        for symbol in symbols:
            volumes[symbol,day]=rank(rows[symbol,day]['volume'],[rows[s,day]['volume'] for s in symbols])
        if i<11:
            continue
        values={}
        for symbol in symbols:
            history=[rows[symbol,d] for d in DATES[i-11:i+1]]
            lo=min(r['low']*r['adj_factor'] for r in history)
            hi=max(r['high']*r['adj_factor'] for r in history)
            values[symbol]=(rows[symbol,day]['close']*rows[symbol,day]['adj_factor']-lo)/(hi-lo)
        for symbol in symbols:
            pos[symbol,day]=rank(values[symbol],list(values.values()))
    actual=compute_alpha101_055(bars,sessions=DATES)
    for r in actual.to_dicts():
        i=DATES.index(r['trade_date'])
        if i<16:
            assert r['alpha101_055'] is None
            continue
        x=[pos[r['symbol'],day] for day in DATES[i-5:i+1]]
        y=[volumes[r['symbol'],day] for day in DATES[i-5:i+1]]
        if len(set(x))==1 or len(set(y))==1:
            assert r['alpha101_055'] is None
        else:
            assert r['alpha101_055']==pytest.approx(-statistics.correlation(x,y),abs=1e-12)


def test_scale_split_and_future_invariance():
    bars=sample()
    original=compute_alpha101_055(bars,sessions=DATES)
    scaled=compute_alpha101_055(bars.with_columns(pl.col('adj_factor')*7),sessions=DATES)
    assert_frame_equal(original,scaled,abs_tol=1e-12)
    split=bars.with_columns(*(pl.when(pl.col('trade_date')>=DATES[20]).then(pl.col(k)/2)
        .otherwise(pl.col(k)).alias(k) for k in ('high','low','close')),
        pl.when(pl.col('trade_date')>=DATES[20]).then(2.).otherwise(1.).alias('adj_factor'))
    assert_frame_equal(original,compute_alpha101_055(split,sessions=DATES))
    assert_frame_equal(original.filter(pl.col('trade_date')<=DATES[25]),
        compute_alpha101_055(bars.filter(pl.col('trade_date')<=DATES[25]),sessions=DATES[:26]))


@pytest.mark.parametrize('column,value',[('close',None),('adj_factor',0.),('volume',0.),('high',float('inf'))])
def test_missing_and_invalid_sessions_invalidate_full_window(column,value):
    bars=sample().with_columns(pl.when(pl.col('trade_date')==DATES[20]).then(pl.lit(value))
        .otherwise(pl.col(column)).alias(column))
    result=compute_alpha101_055(bars,sessions=DATES)
    assert result.filter(pl.col('trade_date').is_between(DATES[20],DATES[36]))['alpha101_055'].null_count()==85
    missing=compute_alpha101_055(sample().filter(pl.col('trade_date')!=DATES[20]),sessions=DATES)
    assert missing.filter(pl.col('trade_date').is_between(DATES[20],DATES[36]))['alpha101_055'].null_count()==85


def test_constant_and_flat_null_and_ties():
    bars=sample().with_columns(pl.lit(100.).alias('volume'))
    assert compute_alpha101_055(bars,sessions=DATES)['alpha101_055'].null_count()==bars.height
    flat=sample().with_columns(pl.lit(10.).alias(k) for k in ('high','low','close'))
    assert compute_alpha101_055(flat,sessions=DATES)['position12'].null_count()==flat.height
    ties=compute_alpha101_055(bars,sessions=DATES)
    assert (ties['volume_rank']==.5).all()


def test_config_fixed_and_duplicates_rejected():
    config=tomllib.loads(Path('configs/research/b74_alpha101_055_20260910.toml').read_text())
    validate_alpha101_055(config)
    for section,key,value in [('alpha101_055','range_sessions',10),('factors','directions',[-1]),
        ('alpha101_055','cross_sectional_rank','time_series'),('portfolio','retention_rank',75)]:
        changed=copy.deepcopy(config)
        changed[section][key]=value
        with pytest.raises(ValueError):
            validate_alpha101_055(changed)
    with pytest.raises(ValueError,match='Duplicate'):
        compute_alpha101_055(pl.concat([sample(),sample().head(1)]),sessions=DATES)
