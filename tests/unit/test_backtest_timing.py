import datetime as dt

import polars as pl

from quant.backtest import schedule_next_trading_day


def test_signal_executes_on_next_market_session_not_same_close() -> None:
    targets = pl.DataFrame({
        "as_of": [dt.date(2026, 7, 10), dt.date(2026, 7, 10)],
        "strategy": ["baseline", "baseline"],
        "strategy_version": ["1", "1"],
        "symbol": ["510300.SH", "00700.HK"],
        "weight": [0.5, 0.5],
    })
    calendars = pl.DataFrame({
        "market": ["SH", "SH", "HK", "HK"],
        "date": [
            dt.date(2026, 7, 10), dt.date(2026, 7, 13),
            dt.date(2026, 7, 10), dt.date(2026, 7, 14),
        ],
        "is_open": [True, True, True, True],
        "is_connect_open": [False, False, False, False],
        "is_half_day": [False, False, False, False],
    })
    result = schedule_next_trading_day(targets, calendars)
    by_symbol = {
        row["symbol"]: row["execution_date"] for row in result.iter_rows(named=True)
    }
    assert by_symbol == {
        "510300.SH": dt.date(2026, 7, 13),
        "00700.HK": dt.date(2026, 7, 14),
    }
