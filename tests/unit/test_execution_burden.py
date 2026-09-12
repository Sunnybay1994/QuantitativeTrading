import datetime as dt

import polars as pl
import pytest

from quant.reporting.execution_burden import execution_burden, render_burden


def test_counts_preserve_later_cash_and_distinguish_fills_from_symbols():
    days = [dt.date(2024, 1, i) for i in range(1, 5)]
    nav = pl.DataFrame({'date': days, 'market_value': [0., 100., 0., 200.], 'position_count': [0, 2, 0, 4]})
    trades = pl.DataFrame({'date': [days[1]]*3+[days[3]], 'symbol': ['a', 'a', 'b', 'c'],
        'notional': [4999., 5000., 100., 9000.]})
    result = execution_burden(nav, trades)
    assert result['mean_positions'] == 2  # Exclude initial cash, retain the later zero.
    assert result['fills'] == 4 and result['trade_days'] == 2
    assert result['median_fills_per_trade_day'] == 2
    assert result['median_symbols_per_trade_day'] == 1.5
    assert result['small_fill_fraction'] == .5  # Exactly 5000 is outside the small bucket.
    assert '不是提交订单数' in render_burden([{'variant': 'test', 'cost_multiplier': 1., **result}])
    with pytest.raises(ValueError):
        execution_burden(nav, trades.with_columns(pl.lit(dt.date(2025, 1, 1)).alias('date')))


def test_all_cash_has_unknown_ratios_and_zero_fills():
    nav = pl.DataFrame({'date': [dt.date(2024, 1, 1)], 'market_value': [0.], 'position_count': [0]})
    trades = pl.DataFrame(schema={'date': pl.Date, 'symbol': pl.String, 'notional': pl.Float64})
    result = execution_burden(nav, trades)
    assert result['fills'] == 0 and result['trade_days'] == 0
    assert result['mean_positions'] is None and result['small_fill_fraction'] is None
