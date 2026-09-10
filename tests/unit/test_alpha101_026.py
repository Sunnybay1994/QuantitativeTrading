"""Scalar rank/correlation oracle and strict-window behavior for Alpha101 #26."""

import copy
import datetime as dt
from pathlib import Path
import statistics
import tomllib

import polars as pl
from polars.testing import assert_frame_equal
import pytest

from quant.factors.alpha101_026 import compute_alpha101_026
from quant.factors.classic_sixth_batch import compute_sixth_batch_daily_factors
from quant.research.monthly_alpha101_026 import build_monthly_alpha101_026, validate_alpha101_026


DATES = tuple(dt.date(2023, 1, 1) + dt.timedelta(days=i) for i in range(65))


def sample() -> pl.DataFrame:
    rows = []
    for offset, symbol in enumerate(("600001.SH", "600002.SH")):
        for i, day in enumerate(DATES):
            price = 10. + ((i * 7 + offset * 3) % 13) / 10
            volume = 100. + ((i * 3 + offset * 5) % 11) * 20
            rows.append(dict(symbol=symbol, trade_date=day, open=price, high=price+1, low=price-1,
                close=price+.5, adj_factor=1., volume=volume, amount=volume*(price+.2), source="fixture"))
    return pl.DataFrame(rows)


def rank_last(values: list[float]) -> float:
    rank = 1 + sum(x < values[-1] for x in values) + (values.count(values[-1])-1)/2
    return (rank-1)/4


def scalar(highs: list[float], volumes: list[float], i: int) -> tuple[float | None, float | None]:
    correlations = []
    for end in range(i-2, i+1):
        high_ranks = [rank_last(highs[j-4:j+1]) for j in range(end-4, end+1)]
        volume_ranks = [rank_last(volumes[j-4:j+1]) for j in range(end-4, end+1)]
        correlations.append(None if len(set(high_ranks))==1 or len(set(volume_ranks))==1
                            else statistics.correlation(high_ranks, volume_ranks))
    value = None if None in correlations else -max(correlations)
    return value, correlations[-1]


def test_every_value_matches_scalar_rank_correlation_and_maximum() -> None:
    bars = sample()
    result = compute_alpha101_026(bars, sessions=DATES)
    for symbol in ("600001.SH", "600002.SH"):
        x = bars.filter(pl.col("symbol")==symbol)
        r = result.filter(pl.col("symbol")==symbol)
        assert r.head(10)["alpha101_026"].null_count()==10
        for i in range(10,len(DATES)):
            expected,corr = scalar(x['high'].to_list(),x['volume'].to_list(),i)
            assert r['alpha101_026'][i] == pytest.approx(expected)
            assert r['rank_correlation5'][i] == pytest.approx(corr)
            assert r['high_rank5'][i] == pytest.approx(rank_last(x['high'].to_list()[i-4:i+1]))


def test_rank_ties_are_averaged_and_constant_correlations_are_null() -> None:
    bars=sample().filter(pl.col('symbol')=='600001.SH').with_columns(
        pl.Series('high',[12.,11.,12.,13.,12.]*13))
    result=compute_alpha101_026(bars,sessions=DATES)
    assert result['high_rank5'][4] == .5
    flat=sample().with_columns(pl.lit(15.).alias('high'))
    assert compute_alpha101_026(flat,sessions=DATES)['alpha101_026'].null_count()==flat.height
    rising=sample().filter(pl.col('symbol')=='600001.SH').with_columns(pl.Series('high',[10.+i for i in range(65)]))
    assert compute_alpha101_026(rising,sessions=DATES)['alpha101_026'].null_count()==65


@pytest.mark.parametrize('column,bad',[('high',None),('high',float('inf')),('adj_factor',0.),('volume',0.)])
def test_invalid_bar_invalidates_eleven_session_window(column: str,bad: float | None) -> None:
    x=sample().with_columns(pl.when(pl.col('trade_date')==DATES[25]).then(pl.lit(bad)).otherwise(pl.col(column)).alias(column))
    r=compute_alpha101_026(x,sessions=DATES)
    assert r.filter(pl.col('trade_date').is_between(DATES[25],DATES[35]))['alpha101_026'].null_count()==22
    recovered=r.filter(pl.col('trade_date')==DATES[36])
    original=compute_alpha101_026(sample(),sessions=DATES).filter(pl.col('trade_date')==DATES[36])
    # Rolling covariance updates can differ by one final floating-point bit.
    assert_frame_equal(recovered, original, rel_tol=1e-12, abs_tol=1e-12)


def test_no_missing_session_compression_or_future_lookahead() -> None:
    bars=sample()
    original=compute_alpha101_026(bars,sessions=DATES)
    r=compute_alpha101_026(bars.filter(pl.col('trade_date')!=DATES[25]),sessions=DATES)
    assert r.filter(pl.col('trade_date').is_between(DATES[25],DATES[35]))['alpha101_026'].null_count()==22
    future=bars.with_columns(pl.when(pl.col('trade_date')>DATES[40]).then(99999.).otherwise(pl.col('high')).alias('high'))
    assert compute_alpha101_026(future,sessions=DATES).filter(pl.col('trade_date')<=DATES[40]).equals(
        original.filter(pl.col('trade_date')<=DATES[40]))


def test_month_end_builder_reuses_original_six_and_split_adjusted_high() -> None:
    bars=sample()
    split=bars.with_columns((pl.col('high')/2).alias('high'),pl.lit(2.).alias('adj_factor'))
    assert compute_alpha101_026(split,sessions=DATES).equals(compute_alpha101_026(bars,sessions=DATES))
    monthly=build_monthly_alpha101_026(bars,sessions=DATES,start=DATES[0],end=DATES[-1])
    dates=[dt.date(2023,1,31),dt.date(2023,2,28)]
    assert monthly['trade_date'].unique().sort().to_list()==dates
    old=compute_sixth_batch_daily_factors(bars,sessions=DATES).filter(pl.col('trade_date').is_in(dates))
    assert monthly.select('symbol','trade_date','alpha101_006').equals(old.select('symbol','trade_date','alpha101_006'))


def test_configuration_rejects_direction_windows_and_missing_control() -> None:
    config=tomllib.loads(Path('configs/research/b68_alpha101_026_20260910.toml').read_text())
    validate_alpha101_026(config)
    for section,key,value in [('alpha101_026','maximum_sessions',5),('alpha101_026','constant_correlation','zero'),
        ('factors','directions',[-1]),('portfolio','retention_rank',75),('admission','redundancy_references',[])]:
        changed=copy.deepcopy(config)
        changed[section][key]=value
        with pytest.raises(ValueError,match='fixed positive'):
            validate_alpha101_026(changed)


def test_composition_fixes_b68_values_weights_and_paired_admission() -> None:
    single=tomllib.loads(Path('configs/research/b68_alpha101_026_20260910.toml').read_text())
    config=tomllib.loads(Path('configs/research/b69_alpha101_026_composite_20260910.toml').read_text())
    assert config['alpha101_026']==single['alpha101_026']
    validate_alpha101_026(config)
    for section,key,value in [('factors','directions',[-1,1,-1,-1]),
        ('alpha101_026_composition','weights','optimized'),
        ('alpha101_026_composition','eligibility','three_factor_only'),
        ('admission','require_positive_paired_1x_compounded_increment',False),
        ('admission','comparison','510300'),('portfolio','retention_rank',75)]:
        changed=copy.deepcopy(config)
        changed[section][key]=value
        with pytest.raises(ValueError):
            validate_alpha101_026(changed)


def test_four_factor_complete_pool_is_restandardized_for_three_factor_control() -> None:
    from quant.research.classic_factor_composite import (
        build_equal_weight_zscore_composite, build_monthly_zscore_targets,
    )

    date=dt.date(2023,1,31)
    names=['alpha158_std20','alpha158_roc20','alpha158_rsv20','alpha101_026']
    directions=[-1,1,-1,1]
    data=[[1.,2.,3.,999.],[3.,1.,2.,999.],[2.,3.,1.,-999.],[.9,.1,.4,None]]
    panel=pl.DataFrame({'symbol':['A','B','C','D'],'trade_date':[date]*4,**dict(zip(names,data,strict=True))})
    primary=build_equal_weight_zscore_composite(panel,component_directions=tuple(zip(names,directions,strict=True)))
    paired=build_equal_weight_zscore_composite(primary,component_directions=tuple(zip(names[:3],directions[:3],strict=True)))
    assert primary['symbol'].to_list()==paired['symbol'].to_list()==['A','B','C']
    for i in range(3):
        z=[direction*(values[i]-statistics.mean(values[:3]))/statistics.pstdev(values[:3])
           for direction,values in zip(directions,data,strict=True)]
        assert primary['equal_zscore'][i]==pytest.approx(statistics.mean(z))
        assert paired['equal_zscore'][i]==pytest.approx(statistics.mean(z[:3]))
    for scores in (primary,paired):
        targets=build_monthly_zscore_targets(scores,sessions=(date,dt.date(2023,2,1)),
            start=dt.date(2023,2,1),end=dt.date(2023,2,1),top_k=2,strategy_name='fixture')
        assert 'D' not in targets['symbol'].to_list()
        assert targets['weight'].sum()==1.
