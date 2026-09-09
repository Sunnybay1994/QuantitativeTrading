import datetime as dt
import math

import polars as pl
import pytest

from quant.research.cost_map import (
    aggregate_five_minute_bars,
    hourly_profile,
    overnight_decomposition,
    round_trip_cost,
)


def test_tick_allowance_and_minimum_commission_are_not_double_counted():
    costs = {"order_budget": 100000., "board_lot": 100, "commission_rate": .00025,
             "commission_min": 5., "tick_size": .001, "slippage_ticks_per_side": 1.}
    result = round_trip_cost(10., costs)
    assert result["quantity"] == 10000
    assert result["round_trip_fraction"] == pytest.approx(70 / 100000)
    assert round_trip_cost(10., costs, 2.)["round_trip_fraction"] == pytest.approx(140 / 100000)
    costs["order_budget"] = 1000.
    assert round_trip_cost(10., costs)["round_trip_fraction"] == pytest.approx(10.2 / 1000)


def test_overnight_decomposition_excludes_reference_price_changes():
    dates = [dt.date(2026, 1, day) for day in (5, 6, 7)]
    daily = pl.DataFrame({"symbol": ["A"] * 3, "trade_date": dates, "open": [100., 110., 55.5],
        "close": [100., 111., 56.], "pre_close": [99., 100., 55.5], "volume": [100.] * 3})
    result = overnight_decomposition(daily, dates[0], dates[-1]).row(0, named=True)
    assert result["days"] == 1
    assert result["overnight_log_return"] == pytest.approx(math.log(1.1))
    assert result["intraday_log_return"] == pytest.approx(math.log(111 / 110))


def test_hourly_profile_accounts_for_short_bars_and_rejects_volume_anomaly():
    dates = [dt.date(2026, 1, day) for day in (5, 6)]
    rows = []
    for date, scale in zip(dates, [1., 2.], strict=True):
        for hour, volume in zip([9, 10, 12, 13, 14], [60., 60., 30., 60., 30.], strict=True):
            rows.append({"symbol": "518880.SH", "trade_date": date,
                "bar_start": dt.datetime.combine(date, dt.time(hour, 30)),
                "open": 10., "high": 11., "low": 9., "close": 10.,
                "volume": volume * scale, "session_complete": True})
    daily = pl.DataFrame({"symbol": ["518880.SH"] * 2, "trade_date": dates,
        "high": [11.] * 2, "low": [9.] * 2, "volume": [240.] * 2})
    profile, quality = hourly_profile(pl.DataFrame(rows), daily,
        {"price_tolerance": .00101, "hourly_max_daily_volume_deviation": .1})
    assert quality["valid_days"] == 1 and quality["excluded_days"] == 1
    assert profile["volume_rate_vs_daily_average"].to_list() == pytest.approx([1.] * 5)


def test_five_minute_aggregation_keeps_session_boundaries_and_excludes_missing_bar():
    rows = []
    for day in [5, 6]:
        date = dt.date(2026, 1, day)
        minutes = list(range(570, 690, 5)) + list(range(780, 900, 5))
        if day == 6:
            minutes.pop()
        for minute in minutes:
            rows.append({"symbol": "A", "trade_date": date,
                "bar_start": dt.datetime.combine(date, dt.time(minute // 60, minute % 60)),
                "open": 10., "close": 10., "high": 11., "low": 9., "volume": 5.,
                "session_complete": day == 5})
    result = aggregate_five_minute_bars(pl.DataFrame(rows))
    assert result.height == 5
    assert result["volume"].to_list() == [60., 60., 30., 60., 30.]
    assert result["bar_start"].dt.strftime("%H:%M").to_list() == ["09:30", "10:30", "13:00", "13:30", "14:30"]
