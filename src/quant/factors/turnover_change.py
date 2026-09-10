"""Short-to-long turnover ratio on complete exchange-session windows."""

import datetime as dt

import polars as pl


FACTOR_NAME = "turnover_ratio20_120"


def compute_turnover_change(
    daily_basic: pl.DataFrame, *, sessions: tuple[dt.date, ...],
) -> pl.DataFrame:
    """Unsigned mean(last 20) / mean(last 120); both include the signal session."""
    keys = ["symbol", "trade_date"]
    if not sessions or tuple(sorted(set(sessions))) != sessions:
        raise ValueError("Sessions must be nonempty, unique and increasing")
    if daily_basic.select(keys).is_duplicated().any():
        raise ValueError("Duplicate turnover symbol-date")
    if daily_basic.select(pl.any_horizontal(pl.col(k).is_null() for k in keys).any()).item():
        raise ValueError("Missing turnover symbol-date")
    grid = daily_basic.select("symbol").unique().join(
        pl.DataFrame({"trade_date": sessions}), how="cross",
    ).join(daily_basic.select(*keys, "turnover_rate"), on=keys, how="left", validate="1:1")
    grid = grid.sort(*keys).with_columns(
        pl.when(pl.col("turnover_rate").is_finite() & (pl.col("turnover_rate") >= 0))
        .then(pl.col("turnover_rate")).otherwise(None).alias("_u"),
    ).with_columns(
        pl.col("_u").rolling_mean(20, min_samples=20).over("symbol").alias("_short"),
        pl.col("_u").rolling_mean(120, min_samples=120).over("symbol").alias("_long"),
    ).with_columns(
        pl.when(pl.col("_long") > 0).then(pl.col("_short") / pl.col("_long"))
        .otherwise(None).alias(FACTOR_NAME),
    )
    return grid.select(*keys, FACTOR_NAME)
