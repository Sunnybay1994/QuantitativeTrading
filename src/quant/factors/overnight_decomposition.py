"""Trailing daily overnight/intraday decomposition for monthly stock selection."""

import datetime as dt

import polars as pl


def compute_overnight_decomposition(
    bars: pl.DataFrame, *, sessions: tuple[dt.date, ...], window: int = 20,
) -> pl.DataFrame:
    """Use adjusted opens and closes; missing exchange sessions invalidate windows."""
    if type(window) is not int or window < 1:
        raise ValueError("Window must be a positive integer")
    if not sessions or tuple(sorted(set(sessions))) != sessions:
        raise ValueError("Sessions must be unique and increasing")
    keys = ["symbol", "trade_date"]
    if bars.select(keys).is_duplicated().any():
        raise ValueError("Duplicate symbol-date")
    if bars.select(pl.any_horizontal(pl.col(k).is_null() for k in keys).any()).item():
        raise ValueError("Missing symbol-date")
    valid = pl.all_horizontal(pl.col(c).is_finite() & (pl.col(c) > 0)
                              for c in ("open", "close", "adj_factor"))
    prices = bars.select(*keys,
        pl.when(valid).then(pl.col("open") * pl.col("adj_factor")).alias("_open"),
        pl.when(valid).then(pl.col("close") * pl.col("adj_factor")).alias("_close"))
    grid = bars.select("symbol").unique().join(
        pl.DataFrame({"trade_date": sessions}), how="cross").join(
            prices, on=keys, how="left", validate="1:1").sort(*keys)
    grid = grid.with_columns(pl.col("_close").shift(1).over("symbol").alias("_prior"))
    # Share a complete cohort across both components and the total-return comparator.
    complete = pl.all_horizontal(pl.col(c).is_finite() & (pl.col(c) > 0)
                                 for c in ("_open", "_close", "_prior"))
    grid = grid.with_columns(
        pl.when(complete).then((pl.col("_open") / pl.col("_prior")).log()).alias("_overnight"),
        pl.when(complete).then((pl.col("_close") / pl.col("_open")).log()).alias("_intraday"),
    ).with_columns(
        pl.col("_overnight").rolling_sum(window, min_samples=window).over("symbol").alias("_on_sum"),
        pl.col("_intraday").rolling_sum(window, min_samples=window).over("symbol").alias("_id_sum"),
    )
    return grid.select(*keys,
        (pl.col("_on_sum").exp() - 1).alias("overnight_return_20"),
        (pl.col("_id_sum").exp() - 1).alias("intraday_return_20"),
        ((pl.col("_on_sum") + pl.col("_id_sum")).exp() - 1).alias("total_return_20"))
