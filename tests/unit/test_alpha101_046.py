import copy
import datetime as dt
from pathlib import Path
import statistics
import tomllib

import polars as pl
from polars.testing import assert_frame_equal
import pytest

from quant.factors.alpha101_046 import compute_alpha101_046
from quant.research.monthly_alpha101_046 import build_monthly_alpha101_046, validate_alpha101_046

DATES = tuple(dt.date(2023, 1, 1)+dt.timedelta(days=i) for i in range(65))


def sample():
    return pl.DataFrame([dict(symbol=symbol, trade_date=day, close=10.+((i*7+j*3)%19)/4,
        open=10.+i/100, high=16., low=9., volume=100.+(i%7)*20, amount=1000., adj_factor=1., source="fixture")
        for j,symbol in enumerate(('600001.SH','600002.SH')) for i,day in enumerate(DATES)])


def test_scalar_formula_matches_every_valid_observation():
    bars=sample().with_columns(pl.when(pl.col('trade_date')>=DATES[30]).then(2.).otherwise(1.).alias('adj_factor'))
    result=compute_alpha101_046(bars,sessions=DATES)
    for symbol in ('600001.SH','600002.SH'):
        source=bars.filter(pl.col('symbol')==symbol).to_dicts()
        actual=result.filter(pl.col('symbol')==symbol)
        assert actual.head(20)['alpha101_046'].null_count()==20
        for i in range(20,len(DATES)):
            prices={k:source[i-k]['close']*source[i-k]['adj_factor']/source[i]['adj_factor'] for k in (0,1,10,20)}
            slope=(prices[20]-prices[10])/10-(prices[10]-prices[0])/10
            expected=-1. if slope>.25 else 1. if slope<0 else -(prices[0]-prices[1])
            assert actual['alpha101_046'][i]==pytest.approx(expected)
            assert actual['slope_difference'][i]==pytest.approx(slope)


@pytest.mark.parametrize('first,expected,branch',[(12.6,-1.,'above_quarter'),(9.9,1.,'below_zero'),
    (12.5,-.4,'negative_daily_change'),(10.,-.4,'negative_daily_change')])
def test_threshold_boundaries_are_strict(first,expected,branch):
    prices=[10.]*21
    prices[0],prices[19]=first,9.6
    x=sample().filter((pl.col('symbol')=='600001.SH') & pl.col('trade_date').is_in(DATES[:21])).with_columns(pl.Series('close',prices))
    last=compute_alpha101_046(x,sessions=DATES[:21]).tail(1)
    assert last['alpha101_046'].item()==pytest.approx(expected)
    assert last['branch'].item()==branch


def test_adjustment_units_cancel_and_split_uses_signal_day_scale():
    bars=sample()
    a=compute_alpha101_046(bars,sessions=DATES)
    b=compute_alpha101_046(bars.with_columns(pl.col('adj_factor')*17),sessions=DATES)
    assert_frame_equal(a,b,rel_tol=1e-12,abs_tol=1e-12)
    flat=bars.with_columns(pl.when(pl.col('trade_date')>=DATES[30]).then(5.).otherwise(10.).alias('close'),
        pl.when(pl.col('trade_date')>=DATES[30]).then(2.).otherwise(1.).alias('adj_factor'))
    values=compute_alpha101_046(flat,sessions=DATES).filter(pl.col('trade_date')>=DATES[20])
    assert values['alpha101_046'].abs().max()==0.


@pytest.mark.parametrize('column,bad',[('close',None),('close',float('inf')),('adj_factor',0.),('volume',0.)])
def test_invalid_observation_invalidates_all_twenty_one_sessions(column,bad):
    bars=sample().with_columns(pl.when(pl.col('trade_date')==DATES[25]).then(pl.lit(bad)).otherwise(pl.col(column)).alias(column))
    result=compute_alpha101_046(bars,sessions=DATES)
    assert result.filter(pl.col('trade_date').is_between(DATES[25],DATES[45]))['alpha101_046'].null_count()==42
    assert result.filter(pl.col('trade_date')==DATES[46])['alpha101_046'].null_count()==0


def test_missing_session_and_future_data_do_not_change_prior_scores():
    bars=sample()
    missing=compute_alpha101_046(bars.filter(pl.col('trade_date')!=DATES[25]),sessions=DATES)
    assert missing.filter(pl.col('trade_date').is_between(DATES[25],DATES[45]))['alpha101_046'].null_count()==42
    original=compute_alpha101_046(bars,sessions=DATES)
    future=bars.with_columns(pl.when(pl.col('trade_date')>DATES[40]).then(1234.).otherwise(pl.col('close')).alias('close'))
    assert original.filter(pl.col('trade_date')<=DATES[40]).equals(
        compute_alpha101_046(future,sessions=DATES).filter(pl.col('trade_date')<=DATES[40]))
    with pytest.raises(ValueError,match='Duplicate'):
        compute_alpha101_046(pl.concat([bars,bars.head(1)]),sessions=DATES)


def test_config_is_fixed_and_monthly_output_keeps_control():
    config=tomllib.loads(Path('configs/research/b71_alpha101_046_20260910.toml').read_text())
    validate_alpha101_046(config)
    for section,key,value in [('alpha101_046','upper_threshold',.2),('alpha101_046','price','future_adjusted_close'),
        ('alpha101_046','minimum_valid_bars',20),('factors','directions',[-1]),('portfolio','retention_rank',75)]:
        changed=copy.deepcopy(config)
        changed[section][key]=value
        with pytest.raises(ValueError):
            validate_alpha101_046(changed)
    monthly=build_monthly_alpha101_046(sample(),sessions=DATES,start=DATES[0],end=DATES[-1])
    assert 'alpha101_006' in monthly.columns
    assert monthly['trade_date'].n_unique()==2
    direct=compute_alpha101_046(sample(),sessions=DATES).filter(pl.col('trade_date').is_in(monthly['trade_date'].unique()))
    assert monthly.select(direct.columns).equals(direct)


def test_composition_preserves_frozen_factor_and_requires_matched_increment():
    config=tomllib.loads(Path('configs/research/b72_alpha101_046_composite_20260910.toml').read_text())
    prior=tomllib.loads(Path('configs/research/b71_alpha101_046_20260910.toml').read_text())
    for section in ('alpha101_046','data','universe','costs','walk_forward','portfolio'):
        assert config[section]==prior[section]
    validate_alpha101_046(config)
    for section,key,value in [('alpha101_046','upper_threshold',.3),('alpha101_046_composition','weights','optimized'),
        ('alpha101_046_composition','eligibility','three_factor_only'),('admission','comparison','510300'),
        ('admission','require_positive_paired_1x_compounded_increment',False),('portfolio','retention_rank',75)]:
        changed=copy.deepcopy(config)
        changed[section][key]=value
        with pytest.raises(ValueError):
            validate_alpha101_046(changed)


def test_both_composites_use_the_same_complete_cohort_and_own_standardization():
    from quant.research.classic_factor_composite import (
        build_equal_weight_zscore_composite, build_monthly_zscore_targets,
    )
    date=dt.date(2023,1,31)
    names=['alpha158_std20','alpha158_roc20','alpha158_rsv20','alpha101_046']
    directions=[-1,1,-1,1]
    columns=[[1.,2.,3.,999.],[3.,1.,2.,999.],[2.,3.,1.,-999.],[.9,.1,.4,None]]
    panel=pl.DataFrame({'symbol':['A','B','C','D'],'trade_date':[date]*4,**dict(zip(names,columns,strict=True))})
    primary=build_equal_weight_zscore_composite(panel,component_directions=tuple(zip(names,directions,strict=True)))
    paired=build_equal_weight_zscore_composite(primary,component_directions=tuple(zip(names[:3],directions[:3],strict=True)))
    assert primary['symbol'].to_list()==paired['symbol'].to_list()==['A','B','C']
    for i in range(3):
        z=[direction*(values[i]-statistics.mean(values[:3]))/statistics.pstdev(values[:3])
           for direction,values in zip(directions,columns,strict=True)]
        assert primary['equal_zscore'][i]==pytest.approx(statistics.mean(z))
        assert paired['equal_zscore'][i]==pytest.approx(statistics.mean(z[:3]))
    for scored in (primary,paired):
        targets=build_monthly_zscore_targets(scored,sessions=(date,dt.date(2023,2,1)),
            start=dt.date(2023,2,1),end=dt.date(2023,2,1),top_k=2,strategy_name='fixture')
        assert 'D' not in targets['symbol'].to_list()
        assert targets['weight'].sum()==1.
