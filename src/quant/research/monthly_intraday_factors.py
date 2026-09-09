"""Load the frozen minute pool for the monthly factor runner."""

import datetime as dt
import hashlib
import io
from pathlib import Path
from typing import Any, cast

import polars as pl

from quant.data.stock_intraday_repository import read_stock_five_minute_pool, reconcile_five_minute_days
from quant.factors.intraday_low_frequency import compute_intraday_low_frequency_factors
from quant.research.lightweight_run import ResearchInputDigestV1


def read_monthly_intraday_factors(
    *, data_root: Path, settings: dict[str, Any], candidates: tuple[str, ...],
    sessions: tuple[dt.date, ...], start: dt.date, end: dt.date,
    daily_bars: pl.DataFrame,
) -> tuple[pl.DataFrame, ResearchInputDigestV1]:
    if (settings["source"] != "baostock" or settings["frequency"] != "5m"
        or settings["required_bars_per_day"] != 48 or settings["smart_bar_count"] != 10
        or settings["tail_start"] != "14:30" or settings["opening_end"] != "10:00"
        or settings["daily_reference"] != "tushare_unadjusted"
        or settings["inconsistent_day"] != "invalidate_rolling_window"):
        raise ValueError("Unsupported monthly minute-factor settings")
    minute = read_stock_five_minute_pool(
        data_root, symbols=candidates, start=start, end=end,
        expected_traded_days=daily_bars.filter(pl.col("volume") > 0),
    ).sort("symbol", "bar_start")
    # Hash the actual input as Parquet bytes without creating millions of Python rows.
    with io.BytesIO() as payload:
        minute.write_parquet(payload)
        digest = ResearchInputDigestV1(
            name="stock-five-minute-bars", rows=minute.height,
            min_date=cast(dt.date | None, minute["trade_date"].min()),
            max_date=cast(dt.date | None, minute["trade_date"].max()),
            content_sha256=hashlib.sha256(payload.getbuffer()).hexdigest(),
        )
    quality = reconcile_five_minute_days(minute, daily_bars,
        close_tolerance=settings["maximum_daily_close_error"],
        volume_tolerance=settings["maximum_daily_volume_relative_error"],
        amount_tolerance=settings["maximum_daily_amount_relative_error"])
    daily = compute_intraday_low_frequency_factors(
        minute.join(quality.select("symbol", "trade_date", "daily_reconciled"),
                    on=["symbol", "trade_date"], how="left", validate="m:1"),
        sessions=sessions, window=settings["window_sessions"],
    ).join(quality, on=["symbol", "trade_date"], how="left", validate="1:1")
    return daily, digest
