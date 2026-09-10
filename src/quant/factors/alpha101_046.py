"""Alpha101 #46 with prices expressed in the current session's yuan scale."""

import datetime as dt

import polars as pl


def compute_alpha101_046(bars: pl.DataFrame, *, sessions: tuple[dt.date, ...]) -> pl.DataFrame:
    """Require 21 consecutive tradable observations; normalize adjustments as of each row."""
    keys = ["symbol", "trade_date"]
    if not sessions or tuple(sorted(set(sessions))) != sessions:
        raise ValueError("Sessions must be nonempty, unique and increasing")
    if bars.select(keys).is_duplicated().any():
        raise ValueError("Duplicate stock bars")
    if bars.select(pl.any_horizontal(pl.col(k).is_null() for k in keys).any()).item():
        raise ValueError("Missing stock bar keys")
    adjusted = pl.col("close") * pl.col("adj_factor")
    valid = pl.all_horizontal(pl.col(k).is_finite() & (pl.col(k) > 0)
                              for k in ("close", "adj_factor", "volume")) & adjusted.is_finite()
    grid = bars.select("symbol").unique().join(pl.DataFrame({"trade_date": sessions}), how="cross").join(
        bars.select(*keys, "close", "adj_factor", "volume"), on=keys, how="left", validate="1:1",
    ).sort(*keys).with_columns(pl.when(valid).then(adjusted).otherwise(None).alias("_price"))
    grid = grid.with_columns(
        pl.col("_price").is_not_null().cast(pl.Int64).rolling_sum(21).over("symbol").alias("valid_bars"),
        *((pl.col("_price").shift(k).over("symbol") / pl.col("adj_factor")).alias(f"close_lag{k}")
          for k in (0, 1, 10, 20)),
    ).with_columns(
        (((pl.col("close_lag20") - pl.col("close_lag10")) / 10)
         - ((pl.col("close_lag10") - pl.col("close_lag0")) / 10)).alias("slope_difference"),
        (pl.col("close_lag0") - pl.col("close_lag1")).alias("close_change1"),
    ).with_columns(
        pl.when(pl.col("slope_difference") > .25).then(-1.)
        .when(pl.col("slope_difference") < 0).then(1.)
        .otherwise(-pl.col("close_change1")).alias("_score"),
        pl.when(pl.col("slope_difference") > .25).then(pl.lit("above_quarter"))
        .when(pl.col("slope_difference") < 0).then(pl.lit("below_zero"))
        .otherwise(pl.lit("negative_daily_change")).alias("_branch"),
    ).with_columns(
        pl.when((pl.col("valid_bars") == 21) & pl.all_horizontal(
            pl.col(k).is_finite() for k in ("_score", "slope_difference", "close_change1",
                                           "close_lag0", "close_lag1", "close_lag10", "close_lag20")))
        .then(pl.col("_score")).otherwise(None).alias("alpha101_046"),
    ).with_columns(pl.when(pl.col("alpha101_046").is_not_null()).then(pl.col("_branch")).alias("branch"))
    return grid.select(*keys, "alpha101_046", "valid_bars", "slope_difference", "close_change1", "branch",
                       *[f"close_lag{k}" for k in (0, 1, 10, 20)])
