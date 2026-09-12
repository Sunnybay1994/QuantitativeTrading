import datetime as dt

import polars as pl
import pytest

from quant.reporting.registered_stress_windows import evaluate


def frames():
    dates = [dt.date(2024, 1, day) for day in range(1, 9)]
    nav = pl.DataFrame({'date': dates, 'unit_nav': [1., 1., 1., .9, .9, .9, .9, .9],
                        'market_value': [0., 0., 100., 0., 0., 0., 0., 0.]})
    return nav, pl.DataFrame({'date': dates, 'unit_nav': [1.] * 8})


def test_cash_windows_and_boundary_sale_loss():
    nav, benchmark = frames()
    windows = [{'name': name, 'start': dt.date(2024, 1, low), 'end': dt.date(2024, 1, high)}
               for name, low, high in [('before', 1, 2), ('sale', 4, 4), ('cash', 5, 8)]]
    before, sale, cash = evaluate(nav, benchmark, windows)
    assert before['applicable'] is False and before['not_worse'] is None
    assert sale['applicable'] is True and sale['not_worse'] is False
    assert sale['strategy_return'] == pytest.approx(-.1)
    assert sale['strategy_drawdown'] == pytest.approx(-.1)
    assert cash['reason'] == 'cash_only_window' and cash['not_worse'] is None


def test_partial_history_and_wrong_benchmark_are_not_passes():
    nav, benchmark = frames()
    windows = [{'name': 'partial', 'start': dt.date(2023, 12, 31), 'end': dt.date(2024, 1, 5)}]
    assert evaluate(nav, benchmark, windows)[0]['reason'] == 'incomplete_history'
    with pytest.raises(ValueError, match='aligned'):
        evaluate(nav, benchmark.tail(7), windows)
    with pytest.raises(ValueError, match='return index'):
        evaluate(nav, nav, windows)
