"""Turnover stability computed over complete exchange-session windows."""

import datetime as dt

import polars as pl


def compute_turnover_variability(
    daily_basic: pl.DataFrame, *, sessions: tuple[dt.date, ...], window: int = 20,
) -> pl.DataFrame:
    """Return unsigned CV; the strategy applies the pre-registered negative direction."""
    if type(window) is not int or window < 2:
        raise ValueError("Turnover window must be an integer of at least two sessions")
    if not sessions or tuple(sorted(set(sessions))) != sessions:
        raise ValueError("Sessions must be nonempty, unique and increasing")
    keys = ["symbol", "trade_date"]
    if daily_basic.select(keys).is_duplicated().any():
        raise ValueError("Duplicate turnover symbol-date")
    if daily_basic.select(pl.any_horizontal(pl.col(k).is_null() for k in keys).any()).item():
        raise ValueError("Missing turnover symbol-date")
    grid = daily_basic.select("symbol").unique().join(
        pl.DataFrame({"trade_date": sessions}), how="cross",
    ).join(daily_basic.select(*keys, "turnover_rate"), on=keys, how="left", validate="1:1")
    grid = grid.sort(*keys).with_columns(
        pl.when(pl.col("turnover_rate").is_finite() & (pl.col("turnover_rate") >= 0))
        .then(pl.col("turnover_rate") / 100.0).otherwise(None).alias("_u"),
    ).with_columns(
        pl.col("_u").rolling_mean(window, min_samples=window).over("symbol").alias("_mean"),
        pl.col("_u").rolling_std(window, min_samples=window, ddof=0).over("symbol").alias("_std"),
    ).with_columns(
        pl.when(pl.col("_mean") > 0).then(
            pl.when(pl.col("_u").rolling_max(window).over("symbol")
                    == pl.col("_u").rolling_min(window).over("symbol"))
            .then(0.0).otherwise(pl.col("_std") / pl.col("_mean")))
        .otherwise(None).alias("turnover_cv20"),
    )
    return grid.select(*keys, "turnover_cv20")
