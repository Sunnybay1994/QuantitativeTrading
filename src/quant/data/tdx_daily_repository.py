"""Bounded reads for unadjusted TongdaXin daily bars."""

import datetime as dt
from pathlib import Path

import polars as pl


def read_tdx_daily_bars(
    data_root: Path, *, symbol: str, start: dt.date, end: dt.date
) -> pl.DataFrame:
    if (
        len(symbol) != 9
        or not symbol[:6].isdigit()
        or symbol[6:] not in {".SH", ".SZ", ".BJ"}
        or start > end
    ):
        raise ValueError("Invalid TongdaXin daily query")
    path = (
        data_root / "clean/bar_1d_tdx/source=tdx"
        / f"market={symbol[-2:]}" / f"symbol={symbol}" / "data.parquet"
    )
    frame = pl.scan_parquet(path).filter(pl.col("trade_date").is_between(start, end)).collect()
    if not frame.is_empty() and (
        set(frame["symbol"]) != {symbol} or set(frame["source"]) != {"tdx"}
    ):
        raise ValueError("TongdaXin daily partition contains another identity")
    return frame.sort("trade_date")
