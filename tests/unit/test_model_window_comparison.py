import datetime as dt

import polars as pl
import pytest

from quant.reporting.model_window_comparison import window_metrics


def test_common_window_keeps_prior_anchor_first_loss_and_cash():
    days = [dt.date(2023, 1, i) for i in (2, 3, 4, 5)]
    nav = pl.DataFrame({'date': days, 'equity': [200.,180.,180.,198.],
        'unit_nav': [2.,1.8,1.8,1.98], 'market_value': [200.,180.,0.,198.]})
    trades = pl.DataFrame({'date': [days[1]], 'notional': [40.]})
    row = window_metrics(nav, trades, start=days[1], end=days[-1], initial_cash=100.)
    assert row['total_return'] == pytest.approx(-.01)
    assert row['max_drawdown'] == pytest.approx(-.1)
    assert row['sessions'] == 3 and row['cash_sessions'] == 1
    assert row['annualized_one_way_turnover'] == pytest.approx(8.4)
    with pytest.raises(ValueError, match='full requested'):
        window_metrics(nav, trades, start=days[1], end=dt.date(2023,1,6), initial_cash=100.)
