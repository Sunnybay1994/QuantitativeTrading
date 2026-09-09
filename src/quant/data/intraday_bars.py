"""Normalize supplier timestamps into completed unadjusted intraday bars."""

import datetime as dt
from typing import Any

import polars as pl

TZ = dt.timezone(dt.timedelta(hours=8))
SCHEMA: dict[str, Any] = {"symbol": pl.String, "trade_date": pl.Date,
          "bar_start": pl.Datetime("us", "Asia/Shanghai"),
          "bar_end": pl.Datetime("us", "Asia/Shanghai"),
          "open": pl.Float64, "high": pl.Float64, "low": pl.Float64, "close": pl.Float64,
          "volume": pl.Float64, "amount": pl.Float64, "source": pl.String}


def normalize_baostock(frame: pl.DataFrame, symbol: str) -> pl.DataFrame:
    if frame.is_empty():
        return pl.DataFrame(schema=SCHEMA)
    code, market = symbol.split(".")
    if set(frame["code"]) != {f"{market.lower()}.{code}"} or set(frame["adjustflag"]) != {"3"}:
        raise ValueError("Unexpected BaoStock symbol or price adjustment")
    # BaoStock emits all-zero placeholders for intervals without a tradable quote.
    # Keep the supplier response in raw; such placeholders are absent from clean.
    frame = frame.filter(~pl.all_horizontal([
        pl.col(c).cast(pl.Float64) == 0 for c in ("open", "high", "low", "close", "volume", "amount")]))
    result = frame.with_columns(
        pl.col("time").str.slice(0, 14).str.to_datetime("%Y%m%d%H%M%S")
        .dt.replace_time_zone("Asia/Shanghai").alias("bar_end"),
        pl.col("date").str.to_date(),
    ).select(
        pl.lit(symbol).alias("symbol"), pl.col("date").alias("trade_date"),
        (pl.col("bar_end") - pl.duration(minutes=5)).alias("bar_start"), "bar_end",
        *[pl.col(c).cast(pl.Float64) for c in ("open", "high", "low", "close", "volume", "amount")],
        pl.lit("baostock").alias("source"),
    )
    return validate_bars(result)


def normalize_yahoo(payload: dict[str, Any], symbol: str, frequency: str,
                    now: dt.datetime) -> pl.DataFrame:
    result = payload["chart"]["result"][0]
    quote = result["indicators"]["quote"][0]
    minutes = int(frequency[:-1])
    rows = []
    hk = symbol.endswith(".HK")
    close = dt.time(16) if hk else dt.time(15)
    for i, stamp in enumerate(result.get("timestamp", [])):
        start = dt.datetime.fromtimestamp(stamp, TZ)
        # Chart appends a live quote with a non-grid timestamp; it is not a full bar.
        if start.second or start.microsecond or start.minute % min(minutes, 30):
            continue
        end = min(start + dt.timedelta(minutes=minutes), dt.datetime.combine(start.date(), close, TZ))
        values = {c: quote[c][i] for c in ("open", "high", "low", "close", "volume")}
        if end <= start or end > now or any(v is None for v in values.values()):
            continue
        # Hourly supplier bars can straddle lunch (HK 12:30 -> 13:30); retain their clock interval.
        if start.time() < dt.time(9, 30) or start.time() >= close:
            continue
        morning_close = dt.datetime.combine(start.date(), dt.time(12) if hk else dt.time(11, 30), TZ)
        afternoon_open = dt.datetime.combine(start.date(), dt.time(13), TZ)
        if start >= morning_close and end <= afternoon_open:
            continue
        if minutes < 60 and (dt.time(12 if hk else 11, 0 if hk else 30) <= start.time() < dt.time(13)):
            continue
        rows.append({"symbol": symbol, "trade_date": start.date(), "bar_start": start,
                     "bar_end": end, **values, "amount": None, "source": "yahoo"})
    return validate_bars(pl.DataFrame(rows, schema=SCHEMA))


def validate_bars(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.is_empty():
        return frame
    required = [c for c in SCHEMA if c != "amount"]
    if frame.select(required).null_count().sum_horizontal().item() or frame.filter(
        (pl.col("bar_end") <= pl.col("bar_start"))
        | (pl.col("trade_date") != pl.col("bar_end").dt.date())
        | pl.any_horizontal([~pl.col(c).is_finite() | (pl.col(c) <= 0)
                             for c in ("open", "high", "low", "close")])
        | ~pl.col("volume").is_finite() | (pl.col("volume") < 0)
        | (pl.col("high") < pl.max_horizontal("open", "close", "low"))
        | (pl.col("low") > pl.min_horizontal("open", "close", "high"))
    ).height:
        raise ValueError("Invalid intraday OHLCV or interval")
    if frame.select("symbol", "bar_start").is_duplicated().any():
        raise ValueError("Duplicate intraday timestamps")
    return frame.sort("symbol", "bar_start")
