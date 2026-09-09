import datetime as dt
import tomllib
from pathlib import Path

import polars as pl
import pytest

from quant.data.intraday_bars import SCHEMA, TZ
from quant.research.gold_vwap_reversion_design_screen import morning_signal, screen


def bars(day=dt.date(2026, 1, 5)):
    rows = []
    for i, minute in enumerate(list(range(570, 690, 5)) + list(range(780, 900, 5))):
        start = dt.datetime.combine(day, dt.time(minute // 60, minute % 60), TZ)
        price = 10.22 - i * .02 if i < 12 else 10.1 if i == 47 else 10.0
        rows.append({"symbol": "518880.SH", "trade_date": day, "bar_start": start,
                     "bar_end": start + dt.timedelta(minutes=5), "open": price, "high": price,
                     "low": price, "close": price, "volume": 10000.0, "amount": 10000.0 * price,
                     "source": "baostock"})
    return pl.DataFrame(rows, schema=SCHEMA).with_columns(pl.lit(True).alias("session_complete"))


def config():
    return tomllib.loads(Path("configs/research/b34_gold_vwap_reversion_20260909.toml").read_text())


def test_signal_uses_only_completed_morning_bars():
    frame = bars()
    day = frame["trade_date"][0]
    result = morning_signal(frame, day=day, maximum_z=-1)
    assert result["signal"]
    assert result["morning_vwap"] == pytest.approx(10.11)
    assert result["signal_close"] == pytest.approx(10.0)
    changed = frame.with_columns(
        pl.when(pl.col("bar_end") > result["decision_at"]).then(1000.0).otherwise(pl.col(c)).alias(c)
        for c in ("close", "amount", "volume")
    )
    assert morning_signal(changed, day=day, maximum_z=-1) == result
    assert morning_signal(frame.head(12), day=day, maximum_z=-1) == result


def test_constant_or_incomplete_morning_has_no_signal():
    frame = bars().with_columns(pl.lit(10.0).alias("close"), pl.lit(100000.0).alias("amount"))
    day = frame["trade_date"][0]
    result = morning_signal(frame, day=day, maximum_z=-1)
    assert result["z"] is None and not result["signal"]
    assert not morning_signal(bars().slice(1), day=day, maximum_z=-1)["signal"]


def test_entry_is_after_decision_and_costs_share_baseline():
    trades, result = screen(bars(), config())
    row = trades.row(0, named=True)
    assert row["entry_time"].time() == dt.time(10, 35)
    assert row["entry_time"] > row["decision_at"]
    assert row["exit_time"].time() == dt.time(14, 55)
    assert row["gross_return"] == pytest.approx(.01)
    assert row["estimated_cost_1x"] == pytest.approx(.0007)
    assert row["estimated_net_2x"] == pytest.approx(.0086)
    assert result["unconditional_baseline"]["mean_gross_return"] == row["gross_return"]
    assert result["conclusion"] == "REJECTED"  # Only one observation.
    with pytest.raises(ValueError, match="complete"):
        screen(bars().head(47), config())
