"""Adjusted 52-week-high proximity and six-month momentum comparator."""

import datetime as dt

import polars as pl


def compute_high52(
    bars: pl.DataFrame, *, sessions: tuple[dt.date, ...],
    high_window: int = 252, momentum_window: int = 126,
) -> pl.DataFrame:
    """Require complete exchange-session windows; compute only trailing values."""
    if (type(high_window) is not int or type(momentum_window) is not int
        or momentum_window < 1 or high_window <= momentum_window):
        raise ValueError("High window must exceed positive momentum window")
    if not sessions or tuple(sorted(set(sessions))) != sessions:
        raise ValueError("Sessions must be unique and increasing")
    keys = ["symbol", "trade_date"]
    if bars.select(keys).is_duplicated().any():
        raise ValueError("Duplicate symbol-date")
    if bars.select(pl.any_horizontal(pl.col(k).is_null() for k in keys).any()).item():
        raise ValueError("Missing symbol-date")
    valid = (pl.all_horizontal(pl.col(c).is_finite() & (pl.col(c) > 0)
                               for c in ("high", "close", "adj_factor"))
             & (pl.col("high") >= pl.col("close")))
    prices = bars.select(*keys,
        pl.when(valid).then(pl.col("high") * pl.col("adj_factor")).alias("_high"),
        pl.when(valid).then(pl.col("close") * pl.col("adj_factor")).alias("_close"))
    grid = bars.select("symbol").unique().join(
        pl.DataFrame({"trade_date": sessions}), how="cross").join(
            prices, on=keys, how="left", validate="1:1").sort(*keys)
    grid = grid.with_columns(
        pl.col("_high").rolling_max(high_window, min_samples=high_window).over("symbol").alias("_peak"),
        pl.col("_close").is_not_null().cast(pl.Int32).rolling_sum(
            momentum_window + 1, min_samples=momentum_window + 1).over("symbol").alias("_count"),
    )
    return grid.select(*keys,
        (pl.col("_close") / pl.col("_peak")).alias("high52_proximity"),
        pl.when(pl.col("_count") == momentum_window + 1).then(
            pl.col("_close") / pl.col("_close").shift(momentum_window).over("symbol") - 1
        ).alias("momentum_126"))
