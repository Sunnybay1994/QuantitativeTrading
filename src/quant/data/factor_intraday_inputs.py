"""Read available stock minute histories without dropping missing daily keys."""

import datetime as dt
from collections.abc import Iterator
from pathlib import Path

import polars as pl

from quant.data.stock_intraday_repository import read_stock_five_minute_bars, reconcile_five_minute_days
from quant.data.intraday import _complete_stock_dates


def read_factor_minute_inputs(data_root: Path, daily: pl.DataFrame) -> Iterator[pl.DataFrame]:
    """Yield one symbol at a time; absent files/days become null after the left join.

    Existing unreadable files still fail. Source discrepancies invalidate the
    entire day with the same one-tick/one-percent tolerances used by B8.
    """
    start, end = daily["trade_date"].min(), daily["trade_date"].max()
    if not isinstance(start, dt.date) or not isinstance(end, dt.date):
        return
    root = data_root / "clean/bar_intraday/freq=5m"
    # A single-symbol recovery must not enumerate every market partition.
    # Probe only the requested symbols; the full-market caller still visits
    # each symbol once, with the same missing-file semantics.
    for symbol in sorted(set(daily["symbol"])):
        reference = daily.filter(pl.col("symbol") == symbol)
        primary = root / "source=baostock" / f"symbol={symbol}" / "data.parquet"
        fallback = root / "source=tdx" / f"symbol={symbol}" / "data.parquet"
        if not primary.is_file() and not fallback.is_file():
            continue
        minute = (read_stock_five_minute_bars(data_root, symbol=symbol, start=start, end=end)
                  if primary.is_file() else pl.DataFrame())
        complete = _complete_stock_dates(minute) if not minute.is_empty() else set()
        pending = set(reference["trade_date"]) - complete
        if pending and fallback.is_file():
            alternative = read_stock_five_minute_bars(
                data_root, symbol=symbol, start=start, end=end, source="tdx",
            ).filter(pl.col("trade_date").is_in(list(pending)))
            if not alternative.is_empty():
                quality = reconcile_five_minute_days(alternative, reference,
                    close_tolerance=0.01, volume_tolerance=0.01, amount_tolerance=0.01)
                accepted = _complete_stock_dates(alternative) & set(
                    quality.filter(pl.col("daily_reconciled"))["trade_date"])
                if accepted:
                    # Select entire validated days, retaining source provenance. Never
                    # splice TDX zero-trade placeholders into BaoStock source files.
                    alternative = alternative.filter(pl.col("trade_date").is_in(list(accepted)))
                    minute = (pl.concat([minute.filter(~pl.col("trade_date").is_in(list(accepted))),
                                         alternative], how="diagonal_relaxed")
                              if not minute.is_empty() else alternative).sort("bar_start")
        if minute.is_empty():
            continue
        quality = reconcile_five_minute_days(minute, reference,
            close_tolerance=0.01, volume_tolerance=0.01, amount_tolerance=0.01)
        # Recompute reconciliation against this input version, if a prior flag exists.
        minute = minute.drop("daily_reconciled", strict=False)
        yield minute.join(quality.select("symbol", "trade_date", "daily_reconciled"),
                          on=["symbol", "trade_date"], how="left", validate="m:1")
