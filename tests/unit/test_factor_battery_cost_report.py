import datetime as dt

import polars as pl
import pytest

from quant.research.factor_battery_cost_report import compare_nav
from quant.data.factor_benchmarks import read_etf_total_return


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


def test_etf_reference_preserves_first_observed_return_and_cuts_future(tmp_path):
    folder = tmp_path/'clean/factor_benchmarks/fixture'
    folder.mkdir(parents=True)
    dates = [dt.date(2020, 1, day) for day in (2, 3, 6)]
    pl.DataFrame({'symbol': ['510300.SH']*3, 'trade_date': dates,
                  'adjusted_close': [2., 2.2, 9.]}).write_parquet(folder/'prices.parquet')
    result = read_etf_total_return(data_root=tmp_path, snapshot='fixture', end=dates[1])
    assert result['date'].to_list() == [dates[1]]
    assert result['unit_nav'].to_list() == [1.1]
    with pytest.raises(ValueError, match='Invalid ETF'):
        read_etf_total_return(data_root=tmp_path, snapshot='../fixture', end=dates[1])
