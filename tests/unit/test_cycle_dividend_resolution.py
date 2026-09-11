import datetime as dt

import polars as pl
import pytest

from quant.data.stock_execution_inputs import ordinary_holder_distributions, resolve_same_day_dividends


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


@pytest.mark.parametrize(('symbol', 'date', 'ratio'), [
    ('000035.SZ', dt.date(2012, 12, 3), .2596),
    ('000155.SZ', dt.date(2016, 12, 14), 1.7021276),
    ('000520.SZ', dt.date(2014, 7, 31), .5),
    ('000912.SZ', dt.date(2018, 7, 30), 1.6803419),
    ('000972.SZ', dt.date(2013, 2, 25), .6),
    ('002260.SZ', dt.date(2020, 9, 25), 1.1),
    ('300362.SZ', dt.date(2021, 6, 15), 2.5502742),
    ('002219.SZ', dt.date(2022, 6, 23), .75),
    ('002309.SZ', dt.date(2024, 12, 24), 2.45),
])
def test_restructuring_does_not_credit_investor_or_creditor_shares(symbol, date, ratio):
    frame = pl.DataFrame({'symbol': [symbol], 'ex_date': [date], 'div_cash': [0.], 'share_ratio': [ratio]})
    assert ordinary_holder_distributions(frame)['share_ratio'].item() == 0.
    with pytest.raises(ValueError):
        ordinary_holder_distributions(frame.with_columns(pl.lit(ratio+.01).alias('share_ratio')))


def test_jianrui_ordinary_shares_use_confirmed_completion_bound():
    frame = pl.DataFrame({'symbol': ['300116.SZ'], 'ex_date': [dt.date(2020, 4, 1)],
        'record_date': [dt.date(2020, 3, 31)], 'share_list_date': [None],
        'div_cash': [0.], 'share_ratio': [.85]})
    row = ordinary_holder_distributions(frame).row(0, named=True)
    assert row['share_ratio'] == .05
    assert row['share_list_date'] == dt.date(2020, 6, 8)
    assert row['adjust_share_price'] is False
    with pytest.raises(ValueError):
        ordinary_holder_distributions(frame.with_columns(pl.lit(.86).alias('share_ratio')))
