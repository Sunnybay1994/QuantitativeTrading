"""Alpha101 #26: negative three-day maximum of ranked high/volume correlation."""

import datetime as dt

import polars as pl


def _rank_current(column: str) -> pl.Expr:
    current = pl.col(column)
    prior = [current.shift(k).over("symbol") for k in range(5)]
    average_rank = 1 + pl.sum_horizontal((x < current).cast(pl.Float64) for x in prior) + (
        pl.sum_horizontal((x == current).cast(pl.Float64) for x in prior) - 1) / 2
    return pl.when(pl.all_horizontal(x.is_not_null() for x in prior)).then((average_rank - 1) / 4)


def compute_alpha101_026(bars: pl.DataFrame, *, sessions: tuple[dt.date, ...]) -> pl.DataFrame:
    """Use strict 5/5/3 windows; undefined constant-input correlations stay null."""
    keys = ["symbol", "trade_date"]
    if not sessions or tuple(sorted(set(sessions))) != sessions:
        raise ValueError("Sessions must be nonempty, unique and increasing")
    if bars.select(keys).is_duplicated().any():
        raise ValueError("Duplicate stock bars")
    if bars.select(pl.any_horizontal(pl.col(k).is_null() for k in keys).any()).item():
        raise ValueError("Missing stock bar keys")
    high = pl.col("high") * pl.col("adj_factor")
    valid = pl.all_horizontal(pl.col(k).is_finite() & (pl.col(k) > 0)
                               for k in ("high", "adj_factor", "volume")) & high.is_finite()
    grid = bars.select("symbol").unique().join(pl.DataFrame({"trade_date": sessions}), how="cross").join(
        bars.select(*keys, "high", "adj_factor", "volume"), on=keys, how="left", validate="1:1",
    ).sort(*keys).with_columns(
        pl.when(valid).then(high).otherwise(None).alias("_high"),
        pl.when(valid).then(pl.col("volume")).otherwise(None).alias("_volume"),
    ).with_columns(
        _rank_current("_high").alias("high_rank5"), _rank_current("_volume").alias("volume_rank5"),
        pl.col("_high").is_not_null().cast(pl.Int64).rolling_sum(11).over("symbol").alias("valid_bars"),
    ).with_columns(
        pl.rolling_corr("high_rank5", "volume_rank5", window_size=5, ddof=1).over("symbol").alias("_corr"),
    )
    varying = pl.all_horizontal(
        (pl.col(k).rolling_max(5).over("symbol") > pl.col(k).rolling_min(5).over("symbol"))
        & (pl.col(k).is_not_null().cast(pl.Int64).rolling_sum(5).over("symbol") == 5)
        for k in ("high_rank5", "volume_rank5"))
    grid = grid.with_columns(
        pl.when(varying & pl.col("_corr").is_finite() & (pl.col("_corr").abs() <= 1 + 1e-12))
        .then(pl.col("_corr").clip(-1, 1)).otherwise(None).alias("rank_correlation5"),
    ).with_columns(
        pl.when(pl.col("valid_bars") == 11)
        .then(-pl.col("rank_correlation5").rolling_max(3).over("symbol"))
        .otherwise(None).alias("alpha101_026"),
    )
    return grid.select(*keys, "alpha101_026", "valid_bars", "high_rank5", "volume_rank5", "rank_correlation5")
