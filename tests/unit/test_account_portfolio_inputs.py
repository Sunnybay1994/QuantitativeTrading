import datetime as dt

import polars as pl
import pytest

from quant.data.account_portfolio_inputs import daily_diagnostics


def test_only_documented_suspension_explains_absent_quote():
    dates = [dt.date(2021, 10, 21), dt.date(2021, 10, 22), dt.date(2021, 10, 25)]
    calendar = pl.DataFrame({'market': ['SH']*3, 'date': dates, 'is_open': [True]*3})
    frame = pl.DataFrame({'ts_code': ['512890.SH']*2, 'trade_date': ['20211021', '20211025'],
                          'close': [1.639, .801], 'amount': [5345.84, 3943.513]})
    args = dict(symbol='512890.SH', start=dates[0], end=dates[-1], calendar=calendar)
    with pytest.raises(ValueError, match='missing=1'):
        daily_diagnostics(frame, **args)
    result = daily_diagnostics(frame, **args, suspended_dates=(dates[1],))
    assert result['rows'] == 2 and result['expected_sessions'] == 3
    assert result['documented_suspended_dates'] == ['2021-10-22']
    assert result['turnover_cny_min'] == pytest.approx(3943513.)
    with pytest.raises(ValueError, match='missing=1'):
        daily_diagnostics(frame.head(1), **args, suspended_dates=(dates[1],))
