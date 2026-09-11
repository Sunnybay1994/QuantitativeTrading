import datetime as dt

import polars as pl
import pytest

from quant.portfolio.concentration_caps import cap_targets


def test_caps_keep_excess_cash_and_use_exact_signal_industry():
    date = dt.date(2024, 1, 31)
    targets = pl.DataFrame({'as_of': [date]*5, 'symbol': list('ABCDE'),
                            'weight': [.25, .25, .25, .15, .1]})
    industries = targets.select('as_of', 'symbol').with_columns(
        pl.Series('industry_l1', ['one', 'one', 'two', None, '']))
    actual = cap_targets(targets, industries, cash_buffer=.02,
                         single_stock_weight=.2, industry_weight=.3)
    assert actual['weight'].to_list() == pytest.approx([.15, .15, .2, 0., 0.])
    future = industries.with_columns(pl.lit(date+dt.timedelta(days=1)).alias('as_of'))
    assert cap_targets(targets, future, cash_buffer=.02, single_stock_weight=.2,
                       industry_weight=.3)['weight'].sum() == 0


def test_cash_and_invalid_inputs():
    targets = pl.DataFrame({'as_of': [dt.date(2024, 1, 31)]*2, 'symbol': ['A', 'B'],
                            'weight': [.5, .5]})
    industries = targets.select('as_of', 'symbol').with_columns(pl.Series('industry_l1', ['a', 'b']))
    limits = dict(cash_buffer=.02, single_stock_weight=.5, industry_weight=.5)
    actual = cap_targets(targets, industries, **limits)
    assert actual['weight'].to_list() == pytest.approx([.49, .49])
    with pytest.raises(ValueError, match='Duplicate'):
        cap_targets(targets, pl.concat([industries, industries]), **limits)
    with pytest.raises(ValueError, match='Invalid target'):
        cap_targets(targets.with_columns(pl.lit(float('nan')).alias('weight')), industries, **limits)
