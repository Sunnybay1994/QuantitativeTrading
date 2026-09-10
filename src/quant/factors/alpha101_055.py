"""Alpha101 #55: negative correlation of cross-sectional price-position and volume ranks."""

import datetime as dt

import polars as pl


def _cross_rank(column: str) -> pl.Expr:
    value = pl.col(column)
    count = value.count().over("trade_date")
    return pl.when(value.is_null()).then(None).when(count <= 1).then(.5).otherwise(
        (value.rank(method="average").over("trade_date") - 1) / (count - 1))


def compute_alpha101_055(bars: pl.DataFrame, *, sessions: tuple[dt.date, ...]) -> pl.DataFrame:
    """Fixed 12/6 windows, average cross-sectional ranks, undefined correlations null."""
    keys = ["symbol", "trade_date"]
    if not sessions or tuple(sorted(set(sessions))) != sessions:
        raise ValueError("Sessions must be nonempty, unique and increasing")
    if bars.select(keys).is_duplicated().any():
        raise ValueError("Duplicate stock bars")
    if bars.select(pl.any_horizontal(pl.col(k).is_null() for k in keys).any()).item():
        raise ValueError("Missing stock bar keys")
    valid = pl.all_horizontal(pl.col(k).is_finite() & (pl.col(k) > 0)
                              for k in ("high", "low", "close", "adj_factor", "volume"))
    valid &= pl.col("close").is_between(pl.col("low"), pl.col("high"))
    valid &= pl.all_horizontal((pl.col(k) * pl.col("adj_factor")).is_finite()
                               for k in ("high", "low", "close"))
    grid = bars.select("symbol").unique().join(pl.DataFrame({"trade_date": sessions}), how="cross").join(
        bars.select(*keys, "high", "low", "close", "adj_factor", "volume"),
        on=keys, how="left", validate="1:1").sort(*keys).with_columns(
            *(pl.when(valid).then(pl.col(k) * pl.col("adj_factor")).otherwise(None).alias(f"_{k}")
              for k in ("high", "low", "close")),
            pl.when(valid).then(pl.col("volume")).otherwise(None).alias("_volume"),
        ).with_columns(
            pl.col("_low").rolling_min(12).over("symbol").alias("low12"),
            pl.col("_high").rolling_max(12).over("symbol").alias("high12"),
            pl.col("_close").is_not_null().cast(pl.Int64).rolling_sum(17).over("symbol").alias("valid_bars"),
        )
    position = (pl.col("_close") - pl.col("low12")) / (pl.col("high12") - pl.col("low12"))
    grid = grid.with_columns(
        pl.when((pl.col("high12") > pl.col("low12")) & position.is_finite()).then(position)
        .otherwise(None).alias("position12"),
    ).with_columns(_cross_rank("position12").alias("position_rank"),
                   _cross_rank("_volume").alias("volume_rank"))
    grid = grid.with_columns(pl.rolling_corr("position_rank", "volume_rank", window_size=6, ddof=1)
                             .over("symbol").alias("_corr"))
    varying = pl.all_horizontal(
        (pl.col(k).rolling_max(6).over("symbol") > pl.col(k).rolling_min(6).over("symbol"))
        & (pl.col(k).is_not_null().cast(pl.Int64).rolling_sum(6).over("symbol") == 6)
        for k in ("position_rank", "volume_rank"))
    return grid.with_columns(pl.when((pl.col("valid_bars") == 17) & varying & pl.col("_corr").is_finite()
        & (pl.col("_corr").abs() <= 1 + 1e-12)).then(-pl.col("_corr").clip(-1, 1))
        .otherwise(None).alias("alpha101_055")).select(
            *keys, "alpha101_055", "valid_bars", "position12", "position_rank", "volume_rank")
