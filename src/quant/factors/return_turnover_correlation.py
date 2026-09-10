"""Synchronous return/turnover correlation on complete exchange sessions."""

import datetime as dt

import polars as pl


FACTOR_NAME = "return_turnover_corr20"


def compute_return_turnover_correlation(
    bars: pl.DataFrame, daily_basic: pl.DataFrame, *, sessions: tuple[dt.date, ...],
) -> pl.DataFrame:
    """Pearson correlation of 20 simple adjusted returns and same-day turnover."""
    keys = ["symbol", "trade_date"]
    if not sessions or tuple(sorted(set(sessions))) != sessions:
        raise ValueError("Sessions must be nonempty, unique and increasing")
    for table in (bars, daily_basic):
        if table.select(keys).is_duplicated().any():
            raise ValueError("Duplicate symbol-date")
        if table.select(pl.any_horizontal(pl.col(k).is_null() for k in keys).any()).item():
            raise ValueError("Missing symbol-date")
    grid = bars.select("symbol").unique().join(pl.DataFrame({"trade_date": sessions}), how="cross")
    grid = grid.join(bars.select(*keys, "close", "adj_factor"), on=keys, how="left", validate="1:1").join(
        daily_basic.select(*keys, "turnover_rate"), on=keys, how="left", validate="1:1",
    ).sort(*keys).with_columns(
        pl.when(pl.all_horizontal(pl.col(c).is_finite() & (pl.col(c) > 0) for c in ("close", "adj_factor"))
                & (pl.col("close") * pl.col("adj_factor")).is_finite())
        .then(pl.col("close") * pl.col("adj_factor")).otherwise(None).alias("_price"),
    ).with_columns(
        (pl.col("_price") / pl.col("_price").shift(1).over("symbol") - 1).alias("_return"),
    )
    paired = pl.col("_return").is_finite() & pl.col("turnover_rate").is_finite() & (pl.col("turnover_rate") >= 0)
    grid = grid.with_columns(
        pl.when(paired).then(pl.col("_return")).otherwise(None).alias("_r"),
        pl.when(paired).then(pl.col("turnover_rate")).otherwise(None).alias("_u"),
    ).with_columns(
        pl.rolling_corr("_r", "_u", window_size=20, min_samples=20).over("symbol").alias("_corr"),
        pl.col("_r").rolling_var(20, min_samples=20, ddof=0).over("symbol").alias("_rvar"),
        pl.col("_u").rolling_var(20, min_samples=20, ddof=0).over("symbol").alias("_uvar"),
    ).with_columns(
        pl.when((pl.col("_rvar") > 1e-12) & (pl.col("_uvar") > 1e-12) & pl.col("_corr").is_finite())
        .then(pl.col("_corr").clip(-1., 1.)).otherwise(None).alias(FACTOR_NAME),
    )
    return grid.select(*keys, FACTOR_NAME)
