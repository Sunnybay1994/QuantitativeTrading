import datetime as dt

import polars as pl
import pytest

from quant.reporting.calendar_turnover import calendar_turnover, turnover_passes


def test_realized_calendar_turnover_uses_mean_equity_and_includes_cash_days():
    dates = [dt.date(2024, 1, 2), dt.date(2024, 12, 31), dt.date(2025, 1, 2)]
    nav = pl.DataFrame({'date': dates, 'equity': [100., 200., 100.],
                        'market_value': [100., 0., 100.]})
    trades = pl.DataFrame({'date': dates, 'notional': [100., 200., 80.]})
    result = calendar_turnover(nav, trades)
    assert result['annual'][0]['turnover'] == 1.
    assert result['annual'][1]['turnover'] == .4
    assert result['annual'][1]['partial_year'] is True
    assert result['median'] == .7
    assert result['maximum'] == 1.


@pytest.mark.parametrize('turnover,excess,expected', [
    (6., 0., True), (6.017, .0573, True), (8., .05, True),
    (8.001, .50, False), (6.01, .0499, False)])
def test_dated_exception(turnover, excess, expected):
    assert turnover_passes(turnover, excess) is expected
