import datetime as dt
import tomllib
from pathlib import Path

import polars as pl
import pytest

from quant.data.intraday_bars import SCHEMA, TZ
from quant.research.overnight_design_screen import screen_overnight


def fixture_bars(day, price):
    rows = []
    for minute in list(range(570, 690, 5)) + list(range(780, 900, 5)):
        start = dt.datetime.combine(day, dt.time(minute // 60, minute % 60), TZ)
        rows.append({"symbol": "518880.SH", "trade_date": day, "bar_start": start,
            "bar_end": start + dt.timedelta(minutes=5), "open": price, "close": price,
            "high": price, "low": price, "volume": 10000., "amount": 10000 * price, "source": "baostock"})
    return pl.DataFrame(rows, schema=SCHEMA).with_columns(pl.lit(True).alias("session_complete"))


def test_weekend_pair_cost_and_missing_day_not_bridged():
    cfg = tomllib.loads(Path("configs/research/b21_gold_overnight_20260909.toml").read_text())
    dates = [dt.date(2026, 1, d) for d in (9, 12, 13)]
    daily = pl.DataFrame({"trade_date": dates})
    frames = [fixture_bars(d, 10. + i) for i, d in enumerate(dates)]
    trades, summary = screen_overnight(pl.concat(frames), daily, cfg)
    row = trades.row(0, named=True)
    assert row["entry_time"].time() == dt.time(14, 55)
    assert row["exit_time"].time() == dt.time(9, 35)
    assert row["exit_date"] == dates[1]
    assert row["gross_return"] == pytest.approx(.1)
    assert row["estimated_cost_1x"] == pytest.approx(.0007)
    assert row["estimated_net_2x"] == pytest.approx(.0986)
    assert summary["signals"] == 2 and summary["conclusion"] == "REJECTED"  # Too few observations.
    assert screen_overnight(pl.concat([frames[0], frames[2]]), daily, cfg)[1]["signals"] == 0
    assert screen_overnight(pl.concat([frames[0], frames[1].head(47), frames[2]]), daily, cfg)[1]["signals"] == 0
    future = fixture_bars(dt.date(2026, 4, 1), 1000.)
    assert screen_overnight(pl.concat([*frames, future]), daily, cfg)[0].equals(trades)
    dead = pl.concat(frames).with_columns(pl.lit(0.).alias("volume"))
    assert screen_overnight(dead, daily, cfg)[1]["signals"] == 0
