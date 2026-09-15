import datetime as dt
import tomllib
from pathlib import Path

import polars as pl
import pytest

from quant.data.intraday_bars import SCHEMA, TZ
from quant.research.morning_tail_design_screen import screen_morning_tail


def bars(day):
    rows = []
    for i in range(48):
        minute = 570 + i * 5 if i < 24 else 780 + (i - 24) * 5
        start = dt.datetime.combine(day, dt.time(minute // 60, minute % 60), TZ)
        price = 10.5 if i == 47 else 10.
        rows.append({"symbol": "518880.SH", "trade_date": day, "bar_start": start,
            "bar_end": start + dt.timedelta(minutes=5), "open": price, "close": price,
            "high": price, "low": price, "volume": 10000., "amount": 10000 * price, "source": "baostock"})
    return pl.DataFrame(rows, schema=SCHEMA).with_columns(pl.lit(True).alias("session_complete"))


def test_prior_close_includes_overnight_and_fixed_tail_execution():
    config = tomllib.loads(Path("configs/research/b14_gold_morning_tail_20260909.toml").read_text(encoding="utf-8"))
    day = dt.date(2026, 1, 5)
    daily = pl.DataFrame({"symbol": ["518880.SH"], "trade_date": [day], "pre_close": [9.]})
    frame = bars(day)
    trades, summary = screen_morning_tail(frame, daily, config)
    row = trades.row(0, named=True)
    assert row["morning_return"] == pytest.approx(10/9-1)  # Flat opening bars; signal is overnight.
    assert row["signal_time"].time() == dt.time(10)
    assert row["entry_time"].time() == dt.time(14, 30)
    assert row["exit_time"] - row["entry_time"] == dt.timedelta(minutes=25)
    assert row["gross_return"] == pytest.approx(.05)
    assert row["estimated_net_2x"] < row["estimated_net_1x"] < row["estimated_net_0.5x"]
    assert summary["signals"] == 1
    assert screen_morning_tail(frame, daily.with_columns(pl.lit(10.).alias("pre_close")), config)[1]["signals"] == 0
    assert screen_morning_tail(frame.head(47), daily, config)[1]["valid_days"] == 0
    future = pl.concat([frame, bars(dt.date(2026, 4, 1))])
    assert screen_morning_tail(future, daily, config)[0].equals(trades)
    with pytest.raises(ValueError, match="previous daily close"):
        screen_morning_tail(frame, daily.head(0), config)
