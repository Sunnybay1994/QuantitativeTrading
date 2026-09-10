import datetime as dt

import polars as pl
import pytest

from quant.reporting.cycle_stress import benchmark_regimes, path_statistics


def test_initial_loss_recovery_and_calendar_slice_keep_previous_wealth():
    dates = [dt.date(2020, 1, 2) + dt.timedelta(days=i) for i in range(6)]
    nav = pl.DataFrame({'date': dates, 'unit_nav': [.8, .9, 1., 1.2, 1.08, 1.3]})
    full = path_statistics(nav, start=dates[0], end=dates[-1])
    assert full['max_drawdown'] == pytest.approx(-.2)
    assert full['worst_day'] == pytest.approx(-.2)
    assert full['max_drawdown_recovery_date'] == dates[2]
    assert full['longest_underwater_sessions'] == 2
    assert full['max_drawdown_peak_is_initial_capital']
    assert full['worst_5_sessions'] == pytest.approx(.08)
    assert full['expected_shortfall_95'] == pytest.approx(-.2)
    window = path_statistics(nav, start=dates[4], end=dates[5])
    assert window['starting_unit_nav'] == 1.2
    assert window['total_return'] == pytest.approx(1.3/1.2-1)
    assert window['worst_day'] == pytest.approx(-.1)


def test_unrecovered_loss_and_bad_paths():
    dates = [dt.date(2020, 1, i) for i in (2, 3, 6)]
    nav = pl.DataFrame({'date': dates, 'unit_nav': [1.1, .8, .9]})
    result = path_statistics(nav, start=dates[0], end=dates[-1])
    assert result['unrecovered_at_end']
    assert result['max_drawdown_recovery_date'] is None
    assert result['max_drawdown_peak_date'] == dates[0]
    with pytest.raises(ValueError):
        path_statistics(pl.concat([nav, nav.head(1)]), start=dates[0], end=dates[-1])


def test_regime_uses_previous_close_and_keeps_future_prices_out():
    start = dt.date(2019, 1, 1)
    bars = pl.DataFrame({'trade_date': [start+dt.timedelta(days=i) for i in range(225)],
                         'close': [100.+i for i in range(224)]+[1.]})
    regimes = benchmark_regimes(bars)
    assert regimes['regime'][-1] == 'bull'
    assert regimes['regime'][-1] == benchmark_regimes(bars.with_columns(
        pl.when(pl.col('trade_date') == bars['trade_date'][-1]).then(10000.).otherwise(pl.col('close')).alias('close')))['regime'][-1]
