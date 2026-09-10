"""Read available stock minute histories without dropping missing daily keys."""

import datetime as dt
from collections.abc import Iterator
from pathlib import Path

import polars as pl

from quant.data.stock_intraday_repository import read_stock_five_minute_bars, reconcile_five_minute_days


def read_factor_minute_inputs(data_root: Path, daily: pl.DataFrame) -> Iterator[pl.DataFrame]:
    """Yield one symbol at a time; absent files/days become null after the left join.

    Existing unreadable files still fail. Source discrepancies invalidate the
    entire day with the same one-tick/one-percent tolerances used by B8.
    """
    start, end = daily["trade_date"].min(), daily["trade_date"].max()
    if not isinstance(start, dt.date) or not isinstance(end, dt.date):
        return
    root = data_root / "clean/bar_intraday/freq=5m/source=baostock"
    available = {path.parent.name.removeprefix("symbol=") for path in root.glob("symbol=*/data.parquet")}
    for symbol in sorted(set(daily["symbol"]) & available):
        minute = read_stock_five_minute_bars(data_root, symbol=symbol, start=start, end=end)
        if minute.is_empty():
            continue
        quality = reconcile_five_minute_days(minute, daily.filter(pl.col("symbol") == symbol),
            close_tolerance=0.01, volume_tolerance=0.01, amount_tolerance=0.01)
        # Recompute reconciliation against this input version, if a prior flag exists.
        minute = minute.drop("daily_reconciled", strict=False)
        yield minute.join(quality.select("symbol", "trade_date", "daily_reconciled"),
                          on=["symbol", "trade_date"], how="left", validate="m:1")
