import datetime as dt

import polars as pl
import pytest

from quant.reporting.q10_monthly import observed_months


def test_incomplete_month_and_initial_cost_are_not_hidden():
    dates = [dt.date(2026, 9, d) for d in (1, 2, 3)]
    calendar = pl.DataFrame({'date': dates, 'is_open': [True]*3})
    nav = pl.DataFrame({'date': dates[1:], 'unit_nav': [.99, 1.01]})
    result = observed_months(nav, calendar)
    assert result['observed_return'][0] == pytest.approx(.01)
    assert result['complete_month'][0] is False
    assert result['same_period_backtest_return'][0] is None


def test_full_observed_calendar_and_month_boundary_returns():
    dates = [dt.date(2026, 9, 30), dt.date(2026, 10, 8)]
    calendar = pl.DataFrame({'date': dates, 'is_open': [True, True]})
    nav = pl.DataFrame({'date': dates, 'unit_nav': [1.1, 1.21]})
    result = observed_months(nav, calendar)
    assert result['observed_return'].to_list() == pytest.approx([.1, .1])
    assert result['complete_month'].all()


def test_missing_month_does_not_turn_multi_month_return_into_monthly_return():
    dates = [dt.date(2026, 9, 30), dt.date(2026, 10, 30), dt.date(2026, 11, 2)]
    calendar = pl.DataFrame({'date': dates, 'is_open': [True]*3})
    nav = pl.DataFrame({'date': [dates[0], dates[2]], 'unit_nav': [1., 1.2]})
    result = observed_months(nav, calendar)
    assert result['observed_return'][1] is None
    assert result['complete_month'][1] is False
    assert result['month_start_boundary_known'][1] is False
