import datetime as dt
from pathlib import Path
import tomllib

import numpy as np
import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.factors.daily_value import compute_daily_value_factors
from quant.factors.expressions import evaluate_expressions, required_history
from quant.factors.high52 import compute_high52
from quant.factors.information_discreteness import compute_information_discreteness
from quant.factors.library import load_library
from quant.factors.overnight_decomposition import compute_overnight_decomposition
from quant.factors.return_skewness import compute_return_skewness
from quant.factors.return_turnover_correlation import compute_return_turnover_correlation
from quant.factors.reversal_volatility import compute_total_volatility_windows
from quant.factors.turnover_change import compute_turnover_change
from tests.unit.test_daily_value_factors import _daily_basic
from tests.unit.test_factor_expressions import prepared


def definitions():
    names = {row['id'] for row in tomllib.loads(Path('configs/factors/legacy_daily_migration_20260911.toml').read_text())['factors']}
    return [row for row in load_library(Path('configs/factors/library')) if row.id in names]


def reference_frames(bars, basic, sessions):
    return [
        compute_daily_value_factors(basic), compute_total_volatility_windows(bars, sessions=sessions),
        compute_high52(bars, sessions=sessions), compute_turnover_change(basic, sessions=sessions),
        compute_return_skewness(bars, sessions=sessions),
        compute_return_turnover_correlation(bars, basic, sessions=sessions),
        compute_information_discreteness(bars, sessions=sessions),
        compute_overnight_decomposition(bars, sessions=sessions),
    ]


def sample():
    sessions = tuple(dt.date(2019, 9, 1) + dt.timedelta(days=i) for i in range(350))
    rows = []
    for stock in range(3):
        for day, date in enumerate(sessions):
            if stock == 1 and day == 270:
                continue
            factor = 2.0 if day >= 290 else 1.0
            close = (10 + stock * 5 + day * 0.03 + np.sin(day * 1.3 + stock) * .4) / factor
            volume = 1000.0 + (day * 71 + stock * 29) % 500
            rows.append(dict(symbol=f'60000{stock}.SH', trade_date=date, open=close*.99,
                high=close*1.03, low=close*.97, close=close, volume=volume if day!=90 else 0.,
                amount=close*volume if day!=90 else 0., adj_factor=factor, source='tushare'))
    bars = pl.DataFrame(rows)
    panel = bars.select('symbol').unique().join(pl.DataFrame({'trade_date':sessions}), how='cross').join(
        bars, on=['symbol','trade_date'], how='left').sort('symbol','trade_date')
    panel = prepared(panel).with_columns(
        (pl.col('trade_date').dt.day().cast(pl.Float64)/10).alias('turnover_rate'),
        pl.when(pl.col('trade_date').dt.day()==1).then(-1.).otherwise(12.).alias('pe_ttm')).with_columns(
            pl.when(pl.col('close').is_not_null()).then(pl.col(name)).otherwise(None).alias(name)
            for name in ('turnover_rate','pb','pe_ttm','ps_ttm','dividend_yield_ttm','total_market_value','circulating_market_value'))
    fields = _daily_basic().schema
    basic = panel.filter(pl.col('close').is_not_null()).select(
        *[pl.col(name) if name in panel.columns else pl.lit(_daily_basic()[name].item(), dtype=dtype).alias(name)
          for name,dtype in fields.items()])
    return bars, basic, panel, sessions


def test_legacy_batch_matches_original_formulas_with_gaps_and_splits():
    bars, basic, panel, sessions = sample()
    defs = definitions()
    assert len(defs)==17
    actual = evaluate_expressions(panel, {row.id:row.expr for row in defs})
    for frame in reference_frames(bars, basic, sessions):
        names = [row.id for row in defs if row.id in frame.columns]
        expected = panel.select('symbol','trade_date','close').join(frame.select('symbol','trade_date',*names),
            on=['symbol','trade_date'], how='left').with_columns(
                pl.when(pl.col('close').is_not_null()).then(pl.col(name)).otherwise(None).alias(name) for name in names
            ).drop('close').sort('symbol','trade_date')
        # The engine's final consumer writes observed keys; reproduce that scope here.
        observed = panel.filter(pl.col('close').is_not_null()).select('symbol','trade_date')
        assert_frame_equal(actual.select(expected.columns).join(observed,on=['symbol','trade_date'],how='semi'),
            expected.join(observed,on=['symbol','trade_date'],how='semi'),rel_tol=1e-7,abs_tol=1e-10)
    # Independent price-window arithmetic for the two remaining legacy outputs.
    for group in panel.partition_by('symbol',maintain_order=True):
        price=group['adj_close'].to_numpy()
        stock=actual.filter(pl.col('symbol')==group['symbol'][0])
        for i in range(60,len(price)):
            tail=price[i-60:i+1]
            vol=stock['annualized_realized_volatility_60'][i]
            if np.isfinite(tail).all():
                assert vol==pytest.approx(np.std(np.log(tail[1:]/tail[:-1]),ddof=1)*np.sqrt(252),abs=1e-11)
            else:
                assert vol is None
            tail=price[i-20:i+1]
            reversal=stock['reversal_20'][i]
            if np.isfinite(tail).all():
                assert reversal==pytest.approx(1-tail[-1]/tail[0])
            else:
                assert reversal is None


def test_legacy_operators_and_history_are_strict():
    panel=pl.DataFrame({'symbol':['A']*7,'trade_date':[dt.date(2020,1,1)+dt.timedelta(days=i) for i in range(7)],
                        'close':[1.,2.,4.,None,3.,3.,3.]})
    result=evaluate_expressions(panel,{'skew':'ts_skew(close,3)','exp':'exp(log(close))'})
    assert result['skew'].is_null().to_list()==[True,True,False,True,True,True,True]
    assert result['exp'].to_list()==pytest.approx([1.,2.,4.,None,3.,3.,3.])
    assert required_history('delay(ts_skew(close,20),21)')==40
    assert max(row.lookback for row in definitions())==273
    with pytest.raises(ValueError,match='at least three'):
        evaluate_expressions(panel,{'bad':'ts_skew(close,2)'})


def test_expression_groups_preserve_key_order_and_values():
    _, _, panel, _ = sample()
    expressions = {f'factor_{i}': f'ts_mean(adj_close,{i+1})' for i in range(130)}
    actual = evaluate_expressions(panel.reverse(), expressions)
    assert actual.columns == ['symbol','trade_date',*expressions]
    for index in (0,63,64,127,128,129):
        name = f'factor_{index}'
        expected = evaluate_expressions(panel, {name:expressions[name]})
        assert_frame_equal(actual.select(expected.columns), expected)
    constants = evaluate_expressions(panel, {'constant':'1', 'invalid':'0/0'})
    assert constants.height == panel.height
    assert constants['constant'].to_list() == [1.] * panel.height
    assert constants['invalid'].null_count() == panel.height
