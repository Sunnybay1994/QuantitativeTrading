"""Four fixed five-minute-to-daily factors for monthly A-share research."""

import datetime as dt

import polars as pl

FACTOR_NAMES = (
    "intraday_tail_amount20", "intraday_smart_vwap20",
    "intraday_skew20", "intraday_open_amount20",
)
_DAILY = ("tail_amount", "smart_vwap", "skew", "open_amount")
_KEY = ["symbol", "trade_date"]


def compute_intraday_low_frequency_factors(
    bars: pl.DataFrame, *, sessions: tuple[dt.date, ...], window: int = 20,
) -> pl.DataFrame:
    """Compute complete-day factors and means over consecutive exchange sessions.

    Returns exclude the overnight gap. The first bar uses its own open; later
    bars use the previous intraday close. Smart selection uses ten bars, with
    chronological tie breaks. Realized skew is the uncentered realized moment.
    """
    if window < 1 or not sessions or sessions != tuple(sorted(set(sessions))):
        raise ValueError("Invalid minute-factor calendar or rolling window")
    if bars.is_empty():
        return pl.DataFrame(schema={"symbol": pl.String, "trade_date": pl.Date,
            "bars_in_day": pl.UInt32, "valid_day": pl.Boolean,
            **{f"daily_{name}": pl.Float64 for name in _DAILY},
            **{name: pl.Float64 for name in FACTOR_NAMES}})
    if (bars.select("symbol", "trade_date", "bar_start", "bar_end").null_count().sum_horizontal().item()
        or bars.select("symbol", "bar_start").is_duplicated().any()
        or bars.schema["bar_start"] != pl.Datetime("us", "Asia/Shanghai")
        or bars.schema["bar_end"] != pl.Datetime("us", "Asia/Shanghai")):
        raise ValueError("Invalid or duplicate minute-factor timestamps")
    frame = bars.sort("symbol", "bar_start")
    minute = pl.col("bar_start").dt.hour().cast(pl.Int32) * 60 + pl.col("bar_start").dt.minute()
    grid = (minute.is_between(570, 685) | minute.is_between(780, 895)) & (minute % 5 == 0)
    valid = (grid & (pl.col("bar_start").dt.second() == 0)
        & (pl.col("bar_start").dt.microsecond() == 0)
        & (pl.col("bar_start").dt.date() == pl.col("trade_date"))
        & (pl.col("bar_end") - pl.col("bar_start") == pl.duration(minutes=5))
        & pl.all_horizontal([pl.col(c).is_finite() & (pl.col(c) > 0)
                             for c in ("open", "high", "low", "close")])
        & (pl.col("high") >= pl.max_horizontal("open", "close", "low"))
        & (pl.col("low") <= pl.min_horizontal("open", "close", "high"))
        & pl.col("volume").is_finite() & (pl.col("volume") >= 0)
        & pl.col("amount").is_finite() & (pl.col("amount") >= 0)
        & ((pl.col("volume") > 0) == (pl.col("amount") > 0)))
    if "session_complete" in frame.columns:
        valid = valid & pl.col("session_complete")
    frame = frame.with_columns(
        minute.alias("_minute"), valid.fill_null(False).alias("_valid"),
        (pl.col("close") / pl.coalesce(pl.col("close").shift(1).over(_KEY), "open")).log().alias("_r"),
    ).with_columns(
        pl.when(pl.col("volume") > 0).then(pl.col("_r").abs() / pl.col("volume").sqrt()).alias("_smart"),
    ).with_columns(
        (pl.col("_smart").rank(method="ordinal", descending=True).over(_KEY) <= 10).fill_null(False).alias("_chosen"),
    )
    daily = frame.group_by(_KEY).agg(
        pl.len().alias("bars_in_day"), pl.col("_valid").all().alias("valid_day"),
        pl.col("amount").sum().alias("_amount"), pl.col("volume").sum().alias("_volume"),
        pl.col("amount").filter(pl.col("_minute") >= 870).sum().alias("_tail"),
        pl.col("amount").filter(pl.col("_minute") < 600).sum().alias("_opening"),
        pl.col("amount").filter(pl.col("_chosen")).sum().alias("_smart_amount"),
        pl.col("volume").filter(pl.col("_chosen")).sum().alias("_smart_volume"),
        pl.col("_chosen").sum().alias("_chosen_count"),
        pl.col("_r").pow(2).sum().alias("_r2"), pl.col("_r").pow(3).sum().alias("_r3"),
    ).with_columns(
        (pl.col("valid_day") & (pl.col("bars_in_day") == 48) & (pl.col("_amount") > 0)
         & (pl.col("_volume") > 0)).alias("valid_day"),
    ).with_columns(
        (pl.col("_tail") / pl.col("_amount")).alias("daily_tail_amount"),
        (pl.col("_opening") / pl.col("_amount")).alias("daily_open_amount"),
        pl.when((pl.col("_chosen_count") == 10) & (pl.col("_smart_volume") > 0)).then(
            (pl.col("_smart_amount") / pl.col("_smart_volume"))
            / (pl.col("_amount") / pl.col("_volume"))).alias("daily_smart_vwap"),
        pl.when(pl.col("_r2") > 0).then(48**0.5 * pl.col("_r3") / pl.col("_r2").pow(1.5)).alias("daily_skew"),
    ).with_columns([
        pl.when(pl.col("valid_day") & pl.col(f"daily_{name}").is_finite())
        .then(pl.col(f"daily_{name}")).otherwise(None).alias(f"daily_{name}") for name in _DAILY
    ])
    calendar = pl.DataFrame({"trade_date": list(sessions), "_session": range(len(sessions))})
    daily = daily.join(calendar, on="trade_date", how="left", validate="m:1").sort(_KEY)
    if daily["_session"].null_count():
        raise ValueError("Minute-factor day is outside the exchange calendar")
    consecutive = pl.col("_session") - pl.col("_session").shift(window - 1).over("symbol") == window - 1
    daily = daily.with_columns([
        pl.when(consecutive).then(pl.col(f"daily_{name}").rolling_mean(window, min_samples=window).over("symbol"))
        .otherwise(None).alias(factor) for name, factor in zip(_DAILY, FACTOR_NAMES)
    ])
    return daily.select(*_KEY, "bars_in_day", "valid_day", *[f"daily_{name}" for name in _DAILY], *FACTOR_NAMES)
