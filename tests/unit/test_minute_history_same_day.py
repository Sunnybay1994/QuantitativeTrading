"""Same-day Futu top-up queue and year-partition merge."""

import datetime as dt
from pathlib import Path

import polars as pl
import pytest

from quant.data.futu_minute_backfill import merge_clean, normalize
from quant.data import minute_history as module


def _bars(symbol: str, day: str, minute: str = "09:31:00") -> pl.DataFrame:
    code, market = symbol.split(".")
    return pl.DataFrame({
        "code": [f"{market}.{code}"],
        "time_key": [f"{day} {minute}"],
        "open": [10.0], "high": [10.5], "low": [9.5], "close": [10.2],
        "volume": [100.0], "turnover": [1020.0],
    })


def test_merge_clean_keeps_earlier_month(tmp_path: Path) -> None:
    symbol = "600000.SH"
    clean = tmp_path / "data.parquet"
    old = normalize(_bars(symbol, "2026-09-18"), symbol, "2026-09-18", "2026-09-18")
    merge_clean(clean, old)
    new = normalize(_bars(symbol, "2026-10-13"), symbol, "2026-10-13", "2026-10-13")
    merged = merge_clean(clean, new)
    assert merged.height == 2
    assert [str(d) for d in merged["trade_date"].to_list()] == ["2026-09-18", "2026-10-13"]


def test_same_day_queue_priority_inventory_then_liquid(tmp_path: Path) -> None:
    root = tmp_path
    # Inventory symbol missing latest session.
    path = root / "clean/futu_minute/all_market/symbol=000001.SZ/year=2026/data.parquet"
    path.parent.mkdir(parents=True)
    normalize(_bars("000001.SZ", "2026-10-10"), "000001.SZ", "2026-10-10", "2026-10-10").write_parquet(path)
    # Already complete inventory should be skipped.
    done = root / "clean/futu_minute/all_market/symbol=000002.SZ/year=2026/data.parquet"
    done.parent.mkdir(parents=True)
    normalize(_bars("000002.SZ", "2026-10-13"), "000002.SZ", "2026-10-13", "2026-10-13").write_parquet(done)

    ranking = tmp_path / "ranking.parquet"
    caps = tmp_path / "caps.parquet"
    pl.DataFrame({
        "symbol": ["300308.SZ", "000001.SZ", "301526.SZ"],
        "median_amount": [3e10, 1e9, 6e9],
        "mean_amount": [3e10, 1e9, 6e9],
        "days": [60, 60, 60],
        "last_date": [dt.date(2026, 9, 10)] * 3,
    }).write_parquet(ranking)
    pl.DataFrame({
        "symbol": ["300308.SZ", "000001.SZ", "301526.SZ"],
        "circulating_market_value": [1e12, 2e11, 4e10],  # large, large, mid
    }).write_parquet(caps)

    settings = dict(
        liquidity_ranking=str(ranking), market_caps=str(caps),
        mid_float_min=10e9, mid_float_max=50e9, large_float_min=50e9,
        liquid_mid_large_limit=10,
    )
    queue = module.same_day_queue(root, "2026-10-13", settings)
    assert queue[0]["symbol"] == "000001.SZ" and queue[0]["priority"] == 0
    assert queue[0]["gap_start"] == "2026-10-11"
    b_symbols = [q["symbol"] for q in queue if q["priority"] == 1]
    assert b_symbols == ["300308.SZ", "301526.SZ"]  # liquidity order; 000001 already in A
    assert "000002.SZ" not in {q["symbol"] for q in queue}
