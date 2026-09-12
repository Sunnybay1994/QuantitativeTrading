"""Recover independently checked daily-basic fields from bounded same-day raw rows.

This module performs no I/O. The caller supplies exactly the requested stock keys.
Schema-compatible rows retain the existing daily-basic contract; rows with an
unusable float-share denominator expose only independently verified supplements.
"""
from __future__ import annotations

import datetime as dt

import polars as pl

from quant.data.refresh_stocks import normalize_day
from quant.domain import Bar1dSchema, DailyBasic1dSchema

MARKET_VALUE_RELATIVE_TOLERANCE = 1e-6
QUALITY_COLUMNS = (
    "daily_basic_schema_valid", "quality_reason", "cleared_fields",
    "market_value_relative_difference",
)
DAILY_BASIC_COLUMNS = tuple(DailyBasic1dSchema.to_schema().columns)
_BASIC_NUMBERS = (
    "close", "turnover_rate", "turnover_rate_f", "volume_ratio", "pe", "pe_ttm", "pb",
    "ps", "ps_ttm", "dv_ratio", "dv_ttm", "total_share", "float_share", "free_share",
    "total_mv", "circ_mv",
)
_DAILY_NUMBERS = ("open", "high", "low", "close", "vol", "amount")
_INDEPENDENT = {"symbol", "trade_date", "close", "total_shares", "total_market_value", "source"}


def _checked_frame(
    frame: pl.DataFrame, *, name: str, numbers: tuple[str, ...], date: dt.date,
) -> pl.DataFrame:
    if not isinstance(frame, pl.DataFrame) or frame.is_empty():
        raise ValueError(f"{name}: require nonempty raw rows")
    if set(("ts_code", "trade_date", *numbers)) - set(frame.columns):
        raise ValueError(f"{name}: missing raw columns")
    if frame.schema["ts_code"] != pl.String or frame.schema["trade_date"] != pl.String:
        raise ValueError(f"{name}: raw keys must be strings")
    if (frame["trade_date"].null_count() or
            frame["trade_date"].unique().to_list() != [date.strftime("%Y%m%d")]):
        raise ValueError(f"{name}: rows must have the requested date")
    if (frame["ts_code"].null_count() or frame["ts_code"].is_duplicated().any() or
            not frame["ts_code"].str.contains(r"^\d{6}\.(SH|SZ)$").all()):
        raise ValueError(f"{name}: invalid or duplicate requested stock keys")
    if any(frame.schema[col] != pl.Null and not frame.schema[col].is_numeric() for col in numbers):
        raise ValueError(f"{name}: raw numeric fields must be numeric")
    result = frame.with_columns(pl.col(col).cast(pl.Float64) for col in numbers)
    if result.select(pl.any_horizontal(
        pl.col(col).is_not_null() & ~pl.col(col).is_finite() for col in numbers
    ).any()).item():
        raise ValueError(f"{name}: nonfinite numeric input")
    return result


def _positive(frame: pl.DataFrame, columns: tuple[str, ...], *, name: str) -> None:
    if frame.select(pl.any_horizontal(
        pl.col(col).is_null() | (pl.col(col) <= 0) for col in columns
    ).any()).item():
        raise ValueError(f"{name}: required prices, shares and market values must be positive")


def recover_daily_basic_fields(
    *, daily: pl.DataFrame, adjustment: pl.DataFrame, basic: pl.DataFrame, date: dt.date,
) -> pl.DataFrame:
    """Return canonical columns plus explicit row quality, without filling source nulls.

    All three raw frames must contain exactly the same requested keys on ``date``.
    Adjustment raw normally has no close; when supplied, it must also match.
    Total market value is retained from raw, in CNY, after a one-ppm check against
    same-day close times total shares. A failure in those independent inputs rejects
    the call. ``free_share > float_share`` clears free shares and free turnover by
    reusing ``normalize_day``. ``float_share > total_share`` returns a supplement
    with only symbol/date/close/total shares/total market value/source populated.

    Select ``DAILY_BASIC_COLUMNS`` only from rows with
    ``daily_basic_schema_valid=True`` when reading this as ``DailyBasic1dSchema``.
    Supplemental rows intentionally do not satisfy its required float-share fields.
    """
    if type(date) is not dt.date:
        raise ValueError("date must be a calendar date")
    daily = _checked_frame(daily, name="daily", numbers=_DAILY_NUMBERS, date=date)
    extra_close = ("close",) if isinstance(adjustment, pl.DataFrame) and "close" in adjustment else ()
    adjustment = _checked_frame(
        adjustment, name="adjustment", numbers=("adj_factor", *extra_close), date=date,
    )
    basic = _checked_frame(basic, name="daily_basic", numbers=_BASIC_NUMBERS, date=date)
    symbols = set(daily["ts_code"])
    if symbols != set(adjustment["ts_code"]) or symbols != set(basic["ts_code"]):
        raise ValueError("Three raw frames must contain exactly the same requested stock keys")
    _positive(daily, ("open", "high", "low", "close"), name="daily")
    _positive(adjustment, ("adj_factor", *extra_close), name="adjustment")
    _positive(basic, ("close", "total_share", "float_share", "total_mv", "circ_mv"), name="daily_basic")
    if basic.filter(pl.col("free_share").is_not_null() & (pl.col("free_share") <= 0)).height:
        raise ValueError("daily_basic: nonpositive free shares cannot be safely recovered")
    for column in ("turnover_rate", "turnover_rate_f", "volume_ratio", "dv_ratio", "dv_ttm"):
        if basic.filter(pl.col(column).is_not_null() & (pl.col(column) < 0)).height:
            raise ValueError(f"daily_basic: invalid {column}")

    paired = basic.join(daily.select("ts_code", pl.col("close").alias("daily_close")),
                        on="ts_code", validate="1:1")
    if extra_close:
        paired = paired.join(adjustment.select("ts_code", pl.col("close").alias("adjustment_close")),
                             on="ts_code", validate="1:1")
    if paired.filter((pl.col("close") - pl.col("daily_close")).abs() > 1e-8).height:
        raise ValueError("Daily close differs from daily_basic close")
    if extra_close and paired.filter((pl.col("close") - pl.col("adjustment_close")).abs() > 1e-8).height:
        raise ValueError("Adjustment close differs from daily_basic close")

    # Validate actual price/adjustment rows even when no full daily-basic row is safe.
    bars = daily.join(adjustment.select("ts_code", "adj_factor"), on="ts_code", validate="1:1").select(
        pl.col("ts_code").alias("symbol"), pl.lit(date).alias("trade_date"),
        "open", "high", "low", "close", (pl.col("vol") * 100).alias("volume"),
        (pl.col("amount") * 1000).alias("amount"), "adj_factor", pl.lit("tushare").alias("source"),
    )
    if bars.select(pl.any_horizontal(~pl.col(col).is_finite() for col in
                   ("open", "high", "low", "close", "volume", "amount", "adj_factor")).any()).item():
        raise ValueError("Converted price or adjustment fields are nonfinite")
    try:
        Bar1dSchema.validate(bars)
    except Exception as error:
        raise ValueError("Invalid raw price/volume/adjustment evidence") from error

    checked = basic.with_columns(
        (pl.col("total_mv") * 10000).alias("checked_total_market_value"),
        (pl.col("total_share") * 10000).alias("checked_total_shares"),
    ).with_columns(
        ((pl.col("checked_total_market_value") - pl.col("close") * pl.col("checked_total_shares")).abs()
         / pl.col("checked_total_market_value")).alias("market_value_relative_difference"),
        (pl.col("float_share") > pl.col("total_share")).alias("supplement_only"),
    )
    if checked.filter(
        ~pl.col("checked_total_market_value").is_finite() | ~pl.col("checked_total_shares").is_finite() |
        ~pl.col("market_value_relative_difference").is_finite() |
        (pl.col("market_value_relative_difference") > MARKET_VALUE_RELATIVE_TOLERANCE)
    ).height:
        raise ValueError("Total market value fails the one-ppm close-times-total-shares check")
    regular = checked.filter(~pl.col("supplement_only"))
    if regular.filter(pl.col("circ_mv") > pl.col("total_mv")).height:
        raise ValueError("Circulating market value exceeds total; unsafe unrelated field recovery")
    parts = []
    if regular.height:
        regular_symbols = regular["ts_code"].to_list()
        try:
            canonical = normalize_day(
                daily.filter(pl.col("ts_code").is_in(regular_symbols)),
                adjustment.filter(pl.col("ts_code").is_in(regular_symbols)),
                basic.filter(pl.col("ts_code").is_in(regular_symbols)), date=date,
            )["daily_basic"]
        except Exception as error:
            raise ValueError("Remaining daily-basic fields cannot be safely normalized") from error
        quality = regular.select(
            pl.col("ts_code").alias("symbol"), pl.lit(True).alias("daily_basic_schema_valid"),
            pl.when(pl.col("free_share") > pl.col("float_share"))
            .then(pl.lit("free_shares_exceed_float_shares")).otherwise(pl.lit("unchanged_valid_row")).alias("quality_reason"),
            pl.when(pl.col("free_share") > pl.col("float_share"))
            .then(pl.lit("free_float_shares,turnover_rate_free")).otherwise(pl.lit("")).alias("cleared_fields"),
            "market_value_relative_difference",
        )
        parts.append(canonical.join(quality, on="symbol", validate="1:1"))
    supplementary = checked.filter(pl.col("supplement_only"))
    if supplementary.height:
        retained = {
            "symbol": pl.col("ts_code"), "trade_date": pl.lit(date), "close": pl.col("close"),
            "total_shares": pl.col("checked_total_shares"),
            "total_market_value": pl.col("checked_total_market_value"), "source": pl.lit("tushare"),
        }
        parts.append(supplementary.select(
            *[retained.get(col, pl.lit(None, dtype=pl.Float64)).alias(col) for col in DAILY_BASIC_COLUMNS],
            pl.lit(False).alias("daily_basic_schema_valid"),
            pl.lit("float_shares_exceed_total_shares;independent_fields_only").alias("quality_reason"),
            pl.lit(",".join(col for col in DAILY_BASIC_COLUMNS if col not in _INDEPENDENT)).alias("cleared_fields"),
            "market_value_relative_difference",
        ))
    return pl.concat(parts).select(*DAILY_BASIC_COLUMNS, *QUALITY_COLUMNS).sort("trade_date", "symbol")


__all__ = [
    "DAILY_BASIC_COLUMNS", "MARKET_VALUE_RELATIVE_TOLERANCE", "QUALITY_COLUMNS",
    "recover_daily_basic_fields",
]
