import datetime as dt

import polars as pl
import pytest

from quant.research.factor_battery_cost_report import compare_nav


def test_comparison_includes_first_common_day_return():
    dates = [dt.date(2020, 1, day) for day in (2, 3, 6)]
    strategy = pl.DataFrame({'date': dates[1:], 'unit_nav': [.9, 1.1]})
    benchmark = pl.DataFrame({'date': dates, 'unit_nav': [2., 2.2, 2.4]})
    result = compare_nav(strategy, benchmark)
    assert result['sessions'] == 2
    assert result['relative_total_return'] == pytest.approx(1.1/1.2-1)
    assert result['net_cagr_excess'] < 0
    assert compare_nav(strategy, strategy)['net_cagr_excess'] == 0.


def test_comparison_does_not_silently_drop_missing_sessions():
    dates = [dt.date(2020, 1, day) for day in (2, 3, 6)]
    strategy = pl.DataFrame({'date': dates, 'unit_nav': [1., 1.1, 1.2]})
    with pytest.raises(ValueError, match='different session grid'):
        compare_nav(strategy, strategy.filter(pl.col('date') != dates[1]))
