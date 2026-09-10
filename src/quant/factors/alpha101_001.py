"""Alpha101 #1 on complete exchange-session windows, with explicit tie rules."""

import datetime as dt

import polars as pl


def compute_alpha101_001(bars: pl.DataFrame, *, sessions: tuple[dt.date, ...]) -> pl.DataFrame:
    """Rank the oldest-first 1..5 argmax of the conditional squared input.

    Require 25 consecutive valid prices for every observation, even when all
    five conditional inputs use price rather than twenty-return volatility.
    Cross-sectional average ranks use (rank - 1)/(n - 1); singleton rank is .5.
    """
    keys = ["symbol", "trade_date"]
    if not sessions or tuple(sorted(set(sessions))) != sessions:
        raise ValueError("Sessions must be nonempty, unique and increasing")
    if bars.select(keys).is_duplicated().any():
        raise ValueError("Duplicate stock bars")
    if bars.select(pl.any_horizontal(pl.col(k).is_null() for k in keys).any()).item():
        raise ValueError("Missing stock bar keys")
    price = pl.col("close") * pl.col("adj_factor")
    grid = bars.select("symbol").unique().join(pl.DataFrame({"trade_date": sessions}), how="cross").join(
        bars.select(*keys, "close", "adj_factor", "volume"), on=keys, how="left", validate="1:1",
    ).sort(*keys).with_columns(
        pl.when(pl.all_horizontal(pl.col(k).is_finite() & (pl.col(k) > 0)
                                  for k in ("close", "adj_factor", "volume")) & price.is_finite())
        .then(price).otherwise(None).alias("_price"),
    ).with_columns((pl.col("_price") / pl.col("_price").shift(1).over("symbol") - 1).alias("_return"))
    grid = grid.with_columns(
        pl.when(pl.col("_return").is_finite()).then(pl.col("_return")).otherwise(None).alias("_return"),
        pl.col("_price").is_not_null().cast(pl.Int64).rolling_sum(25).over("symbol").alias("valid_prices"),
    ).with_columns(pl.col("_return").rolling_std(20, ddof=1).over("symbol").alias("return_std20"))
    grid = grid.with_columns(
        pl.when(pl.col("_return") < 0).then(pl.col("return_std20"))
        .when(pl.col("_return").is_not_null()).then(pl.col("_price"))
        .otherwise(None).pow(2).alias("conditional_squared"),
    ).with_columns(pl.concat_list(pl.col("conditional_squared").shift(k).over("symbol")
                                  for k in (4, 3, 2, 1, 0)).alias("_window"))
    grid = grid.with_columns(
        pl.when((pl.col("valid_prices") == 25) & pl.col("_window").list.eval(
            pl.element().is_finite().fill_null(False)).list.all())
        .then(pl.col("_window").list.arg_max() + 1).otherwise(None).cast(pl.Float64).alias("argmax_position"),
    ).with_columns(
        pl.col("argmax_position").count().over("trade_date").alias("rank_symbols"),
        pl.col("argmax_position").rank(method="average").over("trade_date").alias("_rank"),
    ).with_columns(
        pl.when(pl.col("argmax_position").is_null()).then(None)
        .when(pl.col("rank_symbols") <= 1).then(0.)
        .otherwise((pl.col("_rank") - 1) / (pl.col("rank_symbols") - 1) - .5).alias("alpha101_001"),
    )
    return grid.select(*keys, "alpha101_001", "argmax_position", "rank_symbols", "valid_prices",
                       "return_std20", "conditional_squared")
