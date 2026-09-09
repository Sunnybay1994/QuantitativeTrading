"""A fixed positive-ROE filter inside the same small-cap/value stock cohort."""

import polars as pl


def select_small_value_quality(
    frame: pl.DataFrame, *, small_fraction: float = .30,
    value_fraction: float = .50, minimum_candidates: int = 50,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Intersect two full-cohort ranks, then apply the sole ROE-sign treatment."""
    if (not 0 < small_fraction <= 1 or not 0 < value_fraction <= 1
        or type(minimum_candidates) is not int or minimum_candidates < 1):
        raise ValueError("Invalid fixed small/value pool settings")
    keys = ["trade_date", "symbol"]
    if frame.is_empty() or frame.select(keys).is_duplicated().any():
        raise ValueError("Expected nonempty unique monthly symbol rows")
    required = ("circulating_market_value", "pb", "pit_roe_ttm")
    bad = frame.filter(~pl.all_horizontal(pl.col(c).is_finite() & pl.col(c).is_not_null()
                                         for c in required)
                       | (pl.col("circulating_market_value") <= 0) | (pl.col("pb") <= 0))
    if bad.height or frame.select(pl.any_horizontal(pl.col(k).is_null() for k in keys).any()).item():
        raise ValueError("Both portfolios need the same complete positive-cap positive-PB cohort")
    ranked = frame.sort("trade_date", "circulating_market_value", "symbol").with_columns(
        pl.col("symbol").cum_count().over("trade_date").alias("small_rank"),
        pl.len().over("trade_date").alias("cohort_size"),
    ).sort("trade_date", "pb", "symbol").with_columns(
        pl.col("symbol").cum_count().over("trade_date").alias("value_rank"))
    paired = ranked.filter(
        (pl.col("small_rank") <= (pl.col("cohort_size") * small_fraction).ceil())
        & (pl.col("value_rank") <= (pl.col("cohort_size") * value_fraction).ceil())
    ).sort("trade_date", "circulating_market_value", "symbol")
    primary = paired.filter(pl.col("pit_roe_ttm") > 0)
    counts = frame.select("trade_date").unique().join(
        primary.group_by("trade_date").len(), on="trade_date", how="left").fill_null(0)
    if counts.filter(pl.col("len") < minimum_candidates).height:
        raise ValueError("Small-value positive-ROE pool cannot fill the fixed target count")
    return primary, paired
