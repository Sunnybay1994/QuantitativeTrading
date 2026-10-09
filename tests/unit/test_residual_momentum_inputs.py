import datetime as dt

import polars as pl
import pytest

from quant.research.residual_momentum_inputs import monthly_panel, month_end_dates


def test_month_ends_come_from_exchange_calendar():
    sessions = (dt.date(2020, 1, 23), dt.date(2020, 2, 3), dt.date(2020, 2, 28))
    assert month_end_dates(sessions, sessions[0], sessions[-1]) == (sessions[0], sessions[-1])


def test_absent_month_does_not_bridge_and_delisted_symbol_remains():
    months = (dt.date(2020, 1, 31), dt.date(2020, 2, 28), dt.date(2020, 3, 31))
    bars = pl.DataFrame({'symbol': ['000001.SZ', '000001.SZ', '600001.SH', '900001.SH'],
        'trade_date': [months[0], months[2], months[0], months[0]],
        'close': [10., 20., 5., 1.], 'adj_factor': [1., 1., 1., 1.]})
    basic = bars.select('symbol', 'trade_date').with_columns(
        pl.lit(100.).alias('total_market_value'), pl.lit(2.).alias('pb'))
    result = monthly_panel(bars, basic, months)
    assert set(result['symbol']) == {'000001.SZ', '600001.SH'}
    assert result['_return'].null_count() == result.height
    assert result.filter(pl.col('symbol') == '600001.SH').height == 3
    # Current endpoint data cannot supply a missing previous-month weight.
    assert result.filter((pl.col('symbol') == '000001.SZ') &
                         (pl.col('trade_date') == months[2]))['_lag_mv'].item() is None


def test_duplicate_month_end_is_rejected():
    day = dt.date(2020, 1, 31)
    bars = pl.DataFrame({'symbol': ['600001.SH'] * 2, 'trade_date': [day] * 2,
                        'close': [10.] * 2, 'adj_factor': [1.] * 2})
    with pytest.raises(ValueError, match='Duplicate'):
        monthly_panel(bars, bars, (day,))
