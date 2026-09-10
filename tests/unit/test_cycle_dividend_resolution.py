import datetime as dt

import polars as pl
import pytest

from quant.data.stock_execution_inputs import resolve_same_day_dividends


@pytest.mark.parametrize(('symbol', 'date', 'values', 'expected'), [
    ('601601.SH', dt.date(2021, 6, 30), [0.1, 1.3], 1.3),
    ('600188.SH', dt.date(2022, 7, 14), [0.4, 2.0], 2.0),
])
def test_total_row_does_not_double_count_special_dividend(symbol, date, values, expected):
    frame = pl.DataFrame({'symbol': [symbol]*2, 'ex_date': [date]*2,
        'ann_date': [date-dt.timedelta(days=8)]*2, 'record_date': [date-dt.timedelta(days=1)]*2,
        'pay_date': [date]*2, 'share_list_date': [None]*2, 'div_cash': values, 'share_ratio': [0.]*2})
    assert resolve_same_day_dividends(frame)['div_cash'].to_list() == [expected]
    with pytest.raises(ValueError):
        resolve_same_day_dividends(frame.with_columns((pl.col('div_cash')+.01).alias('div_cash')))


def test_eve_distribution_has_one_cash_and_share_credit():
    date = dt.date(2020, 6, 9)
    frame = pl.DataFrame({'symbol': ['300014.SZ']*2, 'ex_date': [date]*2,
        'ann_date': [dt.date(2020, 6, 2), dt.date(2020, 6, 3)],
        'record_date': [dt.date(2020, 6, 8)]*2, 'pay_date': [date]*2, 'share_list_date': [date]*2,
        'div_cash': [.170165]*2, 'share_ratio': [.9008738]*2})
    result = resolve_same_day_dividends(frame)
    assert result.height == 1
    assert result['ann_date'].item() == dt.date(2020, 6, 2)
    assert result['share_ratio'].item() == .9008738
    with pytest.raises(ValueError):
        resolve_same_day_dividends(frame.with_columns(pl.lit(.9).alias('share_ratio')))
