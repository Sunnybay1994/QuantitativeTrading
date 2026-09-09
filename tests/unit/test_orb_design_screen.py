import datetime as dt
import tomllib
from pathlib import Path

import polars as pl
import pytest

from quant.data.intraday_bars import SCHEMA, TZ
from quant.research.orb_design_screen import screen_orb


def _bars(day, breakout_index=6):
    rows = []
    for i in range(48):
        minute = 570 + i * 5 if i < 24 else 780 + (i - 24) * 5
        start = dt.datetime.combine(day, dt.time(minute // 60, minute % 60), TZ)
        opening = 10.0 if i <= breakout_index else 10.3
        closing = 10.2 if i == breakout_index else opening
        if i == 47:
            opening = closing = 10.5
        rows.append({"symbol": "518880.SH", "trade_date": day, "bar_start": start,
            "bar_end": start + dt.timedelta(minutes=5), "open": opening, "close": closing,
            "high": max(opening, closing), "low": min(opening, closing),
            "volume": 10000.0, "amount": 10000 * closing, "source": "baostock"})
    return pl.DataFrame(rows, schema=SCHEMA).with_columns(pl.lit(True).alias("session_complete"))


def _config():
    return tomllib.loads(Path("configs/research/b9_gold_orb_feasibility_20260909.toml").read_text(encoding="utf-8"))


def test_orb_uses_next_bar_and_frozen_exit_once_per_day():
    day = dt.date(2026, 1, 5)
    trades, summary = screen_orb(_bars(day), _config())
    assert trades.height == 1
    row = trades.row(0, named=True)
    assert row["signal_time"].time() == dt.time(10, 5)
    assert row["entry_price"] == 10.3
    assert row["signal_close"] == 10.2
    assert row["exit_time"].time() == dt.time(14, 55)
    assert row["gross_return"] == pytest.approx(10.5 / 10.3 - 1)
    assert row["estimated_net_2x"] < row["estimated_net_1x"] < row["estimated_net_0.5x"]
    assert summary["conclusion"] == "REJECTED"  # Fewer than 20 design signals.


def test_orb_rejects_incomplete_days_late_breakouts_and_excludes_future():
    day = dt.date(2026, 1, 5)
    assert screen_orb(_bars(day).head(47), _config())[1]["valid_days"] == 0
    assert screen_orb(_bars(day, breakout_index=44), _config())[1]["signals"] == 0
    bars = _bars(day)
    before = screen_orb(bars, _config())
    after = screen_orb(pl.concat([bars, _bars(dt.date(2026, 4, 1))]), _config())
    assert before[0].equals(after[0])
    assert before[1] == after[1]
