"""Trailing daily return skewness with complete exchange-session windows."""

import datetime as dt

import polars as pl


def compute_return_skewness(bars: pl.DataFrame, *, sessions: tuple[dt.date, ...],
                            window: int = 20) -> pl.DataFrame:
    """Use bias-corrected skew of simple adjusted-close returns; never fill gaps."""
    if type(window) is not int or window < 3:
        raise ValueError("Skew window must be an integer at least three")
    if not sessions or tuple(sorted(set(sessions))) != sessions:
        raise ValueError("Sessions must be unique and increasing")
    keys = ["symbol", "trade_date"]
    if bars.select(keys).is_duplicated().any():
        raise ValueError("Duplicate symbol-date")
    if bars.select(pl.any_horizontal(pl.col(k).is_null() for k in keys).any()).item():
        raise ValueError("Missing symbol-date")
    valid = pl.all_horizontal(pl.col(c).is_finite() & (pl.col(c) > 0) for c in ("close", "adj_factor"))
    prices = bars.select(*keys, pl.when(valid).then(pl.col("close") * pl.col("adj_factor")).alias("_close"))
    grid = bars.select("symbol").unique().join(pl.DataFrame({"trade_date": sessions}), how="cross").join(
        prices, on=keys, how="left", validate="1:1").sort(*keys)
    grid = grid.with_columns((pl.col("_close") / pl.col("_close").shift(1).over("symbol") - 1).alias("_return"))
    grid = grid.with_columns(pl.when(pl.col("_return").is_finite()).then(pl.col("_return")).alias("_return"))
    grid = grid.with_columns(
        pl.col("_return").rolling_skew(window, bias=False, min_samples=window).over("symbol").alias("_skew"),
        pl.col("_return").rolling_std(window, min_samples=window, ddof=0).over("symbol").alias("_std"))
    return grid.select(*keys, pl.when(pl.col("_skew").is_finite() & (pl.col("_std") > 1e-12))
                       .then(pl.col("_skew")).alias("return_skew20"))
