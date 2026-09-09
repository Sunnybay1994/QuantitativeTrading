"""Read the local BaoStock five-minute stock history for low-frequency factors."""

import datetime as dt
from pathlib import Path

import polars as pl


def read_stock_five_minute_bars(
    data_root: Path, *, symbol: str, start: dt.date, end: dt.date,
) -> pl.DataFrame:
    if (len(symbol) != 9 or not symbol[:6].isdigit() or symbol[6:] not in (".SH", ".SZ")
        or start > end):
        raise ValueError("Invalid A-share minute history query")
    path = (data_root / "clean/bar_intraday/freq=5m/source=baostock"
            / f"symbol={symbol}" / "data.parquet")
    return pl.scan_parquet(path).filter(pl.col("trade_date").is_between(start, end)).collect()
