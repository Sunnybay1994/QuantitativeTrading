"""Read local stock minute history for low-frequency factors."""

import datetime as dt
from pathlib import Path

import polars as pl


def read_stock_intraday_bars(
    data_root: Path,
    *,
    symbol: str,
    start: dt.date,
    end: dt.date,
    frequency: str,
    source: str,
) -> pl.DataFrame:
    if (len(symbol) != 9 or not symbol[:6].isdigit()
        or symbol[6:] not in (".SH", ".SZ", ".BJ")
        or start > end):
        raise ValueError("Invalid A-share minute history query")
    if frequency not in {"1m", "5m"} or source not in {"baostock", "tdx"}:
        raise ValueError("Unsupported minute history frequency or source")
    path = (data_root / f"clean/bar_intraday/freq={frequency}/source={source}"
            / f"symbol={symbol}" / "data.parquet")
    frame = pl.scan_parquet(path).filter(pl.col("trade_date").is_between(start, end)).collect()
    if not frame.is_empty() and set(frame["symbol"]) != {symbol}:
        raise ValueError(f"Minute history contains another symbol: {symbol}")
    return frame


def read_stock_five_minute_bars(
    data_root: Path, *, symbol: str, start: dt.date, end: dt.date,
    source: str = "baostock",
) -> pl.DataFrame:
    return read_stock_intraday_bars(
        data_root,
        symbol=symbol,
        start=start,
        end=end,
        frequency="5m",
        source=source,
    )


def read_stock_five_minute_pool(
    data_root: Path, *, symbols: tuple[str, ...], start: dt.date, end: dt.date,
    expected_traded_days: pl.DataFrame, source: str = "baostock",
) -> pl.DataFrame:
    """Read the entire requested pool; partial backfills must not shrink a study."""
    if not symbols or len(set(symbols)) != len(symbols):
        raise ValueError("Invalid minute history pool")
    missing = [symbol for symbol in symbols if not (
        data_root / f"clean/bar_intraday/freq=5m/source={source}" / f"symbol={symbol}" / "data.parquet"
    ).is_file()]
    if missing:
        raise FileNotFoundError(f"Minute history pending for {len(missing)} symbols; first: {missing[:5]}")
    result = pl.concat([read_stock_five_minute_bars(
        data_root, symbol=symbol, start=start, end=end, source=source)
                        for symbol in symbols], how="diagonal_relaxed")
    expected = expected_traded_days.filter(pl.col("symbol").is_in(list(symbols))
        & pl.col("trade_date").is_between(start, end)).select("symbol", "trade_date").unique()
    gaps = expected.join(result.select("symbol", "trade_date").unique(),
                         on=["symbol", "trade_date"], how="anti")
    if gaps.height:
        raise ValueError(f"Minute history missing {gaps.height} known traded symbol-days")
    return result


def reconcile_five_minute_days(
    minute: pl.DataFrame, daily: pl.DataFrame, *, close_tolerance: float,
    volume_tolerance: float, amount_tolerance: float,
) -> pl.DataFrame:
    """Flag inconsistent source days without modifying minute or daily prices."""
    if min(close_tolerance, volume_tolerance, amount_tolerance) < 0:
        raise ValueError("Negative daily reconciliation tolerance")
    key = ["symbol", "trade_date"]
    totals = minute.sort("symbol", "bar_start").group_by(key).agg(
        pl.col("close").last().alias("minute_close"),
        pl.col("volume").sum().alias("minute_volume"),
        pl.col("amount").sum().alias("minute_amount"),
    ).join(daily.select(*key, "close", "volume", "amount"), on=key, how="left", validate="m:1")
    return totals.with_columns(
        (pl.col("minute_close") - pl.col("close")).abs().alias("daily_close_error"),
        (pl.col("minute_volume") / pl.col("volume") - 1).abs().alias("daily_volume_error"),
        (pl.col("minute_amount") / pl.col("amount") - 1).abs().alias("daily_amount_error"),
    ).with_columns((
        pl.all_horizontal([pl.col(c).is_finite() & (pl.col(c) > 0) for c in ("close", "volume", "amount")])
        & (pl.col("daily_close_error") <= close_tolerance + 1e-8)
        & (pl.col("daily_volume_error") <= volume_tolerance + 1e-10)
        & (pl.col("daily_amount_error") <= amount_tolerance + 1e-10)
    ).fill_null(False).alias("daily_reconciled")).select(
        *key, "daily_reconciled", "daily_close_error", "daily_volume_error", "daily_amount_error",
    ).sort(key)
