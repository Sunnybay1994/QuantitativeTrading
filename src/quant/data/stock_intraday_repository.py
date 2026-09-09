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
    frame = pl.scan_parquet(path).filter(pl.col("trade_date").is_between(start, end)).collect()
    if not frame.is_empty() and set(frame["symbol"]) != {symbol}:
        raise ValueError(f"Minute history contains another symbol: {symbol}")
    return frame


def read_stock_five_minute_pool(
    data_root: Path, *, symbols: tuple[str, ...], start: dt.date, end: dt.date,
    expected_traded_days: pl.DataFrame,
) -> pl.DataFrame:
    """Read the entire requested pool; partial backfills must not shrink a study."""
    if not symbols or len(set(symbols)) != len(symbols):
        raise ValueError("Invalid minute history pool")
    missing = [symbol for symbol in symbols if not (
        data_root / "clean/bar_intraday/freq=5m/source=baostock" / f"symbol={symbol}" / "data.parquet"
    ).is_file()]
    if missing:
        raise FileNotFoundError(f"Minute history pending for {len(missing)} symbols; first: {missing[:5]}")
    result = pl.concat([read_stock_five_minute_bars(data_root, symbol=symbol, start=start, end=end)
                        for symbol in symbols], how="diagonal_relaxed")
    expected = expected_traded_days.filter(pl.col("symbol").is_in(list(symbols))
        & pl.col("trade_date").is_between(start, end)).select("symbol", "trade_date").unique()
    gaps = expected.join(result.select("symbol", "trade_date").unique(),
                         on=["symbol", "trade_date"], how="anti")
    if gaps.height:
        raise ValueError(f"Minute history missing {gaps.height} known traded symbol-days")
    return result
