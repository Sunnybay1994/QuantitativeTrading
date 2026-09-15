import datetime as dt
import tomllib
from pathlib import Path

import polars as pl
import pytest

from quant.research.hk_connect_momentum_design_screen import buy_routes_on, screen


def inputs():
    cfg = tomllib.loads(
        Path("configs/research/b29_hk_connect_momentum_design_20260909.toml").read_text(
            encoding="utf-8"
        )
    )
    start, end = dt.date(2024, 1, 1), dt.date(2024, 3, 1)
    days = [start + dt.timedelta(days=number) for number in range((end - start).days + 1)]
    hk = tuple(day for day in days if day.weekday() < 5)
    cfg["research"].update(design_start=dt.date(2024, 2, 1), design_end=dt.date(2024, 2, 23))
    calendar = pl.DataFrame(
        {
            "date": days,
            "can_execute_1430": [
                day.weekday() < 5 and not dt.date(2024, 2, 9) <= day <= dt.date(2024, 2, 18)
                for day in days
            ],
        }
    )
    rows = []
    for symbol, slope in (("A", 0.4), ("B", 0.3), ("C", 0.2), ("D", 0.1)):
        for index, day in enumerate(hk):
            for hour in (13, 14):
                price = 10.0 + index * slope
                rows.append(
                    {
                        "symbol": symbol,
                        "trade_date": day,
                        "bar_start": dt.datetime.combine(day, dt.time(hour, 30)),
                        "open": price,
                        "close": price,
                        "volume": 100.0,
                    }
                )
    intervals = []
    for symbol in "ABCD":
        for route in ("SH_CONNECT", "SZ_CONNECT"):
            if symbol == "A" and route == "SH_CONNECT":
                intervals.extend(
                    [
                        {
                            "symbol": symbol,
                            "route": route,
                            "valid_from": start,
                            "valid_to": dt.date(2024, 2, 5),
                            "buy_eligible": True,
                        },
                        {
                            "symbol": symbol,
                            "route": route,
                            "valid_from": dt.date(2024, 2, 6),
                            "valid_to": end,
                            "buy_eligible": False,
                        },
                    ]
                )
            else:
                intervals.append(
                    {
                        "symbol": symbol,
                        "route": route,
                        "valid_from": start,
                        "valid_to": end,
                        "buy_eligible": symbol == "B" and route == "SZ_CONNECT",
                    }
                )
    return (
        pl.DataFrame(rows),
        hk,
        {symbol: [] for symbol in "ABCD"},
        calendar,
        pl.DataFrame(intervals),
        cfg,
    )


def test_calendar_holding_buy_filter_sell_only_and_cash_slots():
    bars, hk, actions, calendar, intervals, cfg = inputs()
    trades, cycles, summary = screen(bars, hk, actions, calendar, intervals, cfg)
    assert trades["symbol"].to_list() == ["A", "B", "B"]
    first = trades.row(0, named=True)
    assert first["entry_date"] == dt.date(2024, 2, 1)
    assert first["exit_date"] == dt.date(2024, 2, 8)
    assert first["exit_sell_only"] and first["exit_route"] == "SH_CONNECT"
    spring = trades.row(2, named=True)
    assert spring["entry_date"] == dt.date(2024, 2, 8)
    assert spring["exit_date"] == dt.date(2024, 2, 23)
    assert spring["entry_route"] == spring["exit_route"] == "SZ_CONNECT"
    assert spring["calendar_holding_days"] == 15
    assert spring["signal_date"] == dt.date(2024, 2, 7)
    assert hk.index(spring["signal_date"]) - hk.index(spring["reference_date"]) == 20
    expected = (10 + hk.index(dt.date(2024, 2, 23)) * 0.3) / (
        10 + hk.index(dt.date(2024, 2, 8)) * 0.3
    ) - 1
    assert spring["gross_return"] == pytest.approx(expected)
    assert spring["estimated_net_2x"] == pytest.approx(expected - 0.008)
    assert cycles["cash_slots"].to_list() == [1, 2]
    assert cycles["cycle_gross_return"][1] == pytest.approx(expected / 3)
    assert summary["trades"] == 3 and summary["sell_only_exits"] == 1


def test_missing_losing_exit_fails_and_missing_signal_keeps_cash_cycle():
    bars, hk, actions, calendar, intervals, cfg = inputs()
    missing_exit = bars.filter(
        ~(
            (pl.col("symbol") == "B")
            & (pl.col("trade_date") == dt.date(2024, 2, 23))
            & (pl.col("bar_start").dt.hour() == 14)
        )
    )
    with pytest.raises(ValueError, match="Selected execution quote unavailable"):
        screen(missing_exit, hk, actions, calendar, intervals, cfg)
    missing_signal = bars.filter(
        ~(
            (pl.col("symbol") == "D")
            & (pl.col("trade_date") == dt.date(2024, 1, 31))
            & (pl.col("bar_start").dt.hour() == 13)
        )
    )
    trades, cycles, summary = screen(missing_signal, hk, actions, calendar, intervals, cfg)
    assert summary["missing_signal_cycles"] == 1
    assert summary["trades"] == 1
    assert cycles["cash_slots"].to_list() == [3, 2]
    assert trades["symbol"].to_list() == ["B"]


def test_signal_uses_prior_complete_hk_day_even_when_southbound_closed():
    bars, hk, actions, calendar, intervals, cfg = inputs()
    cfg["research"]["design_start"] = dt.date(2024, 2, 19)
    cfg["research"]["design_end"] = dt.date(2024, 2, 26)
    trades = screen(bars, hk, actions, calendar, intervals, cfg)[0]
    assert trades["signal_date"].item() == dt.date(2024, 2, 16)
    assert trades["reference_date"].item() == hk[hk.index(dt.date(2024, 2, 16)) - 20]
    changed = bars.with_columns(
        pl.when(pl.col("trade_date") >= dt.date(2024, 2, 19))
        .then(pl.col("close") * 100)
        .otherwise(pl.col("close"))
        .alias("close")
    )
    assert screen(changed, hk, actions, calendar, intervals, cfg)[0].equals(trades)


def test_unknown_or_duplicate_eligibility_and_calendar_gaps_fail():
    bars, hk, actions, calendar, intervals, cfg = inputs()
    with pytest.raises(ValueError, match="route eligibility"):
        buy_routes_on(
            intervals.filter(pl.col("route") == "SH_CONNECT"), list("ABCD"), dt.date(2024, 2, 1)
        )
    with pytest.raises(ValueError, match="route eligibility"):
        buy_routes_on(pl.concat([intervals, intervals.head(1)]), list("ABCD"), dt.date(2024, 2, 1))
    with pytest.raises(ValueError, match="Incomplete Southbound calendar"):
        screen(
            bars,
            hk,
            actions,
            calendar.filter(pl.col("date") != dt.date(2024, 2, 10)),
            intervals,
            cfg,
        )


def test_dividend_and_nonpositive_scores_cash():
    bars, hk, actions, calendar, intervals, cfg = inputs()
    actions["B"] = [{"date": dt.date(2024, 2, 15), "cash": 1.0, "split": 1.0}]
    trades = screen(bars, hk, actions, calendar, intervals, cfg)[0]
    spring = trades.row(2, named=True)
    assert spring["gross_return"] == pytest.approx(
        (spring["exit_price"] + 1) / spring["entry_price"] - 1
    )
    flat = bars.with_columns(pl.lit(10.0).alias("open"), pl.lit(10.0).alias("close"))
    trades, cycles, summary = screen(
        flat, hk, {symbol: [] for symbol in "ABCD"}, calendar, intervals, cfg
    )
    assert trades.is_empty() and summary["conclusion"] == "REJECTED"
    assert cycles["cash_slots"].to_list() == [3, 3]
