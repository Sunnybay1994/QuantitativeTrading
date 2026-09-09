"""Daily total market size without value or quality filters."""

import polars as pl


def compute_market_size(basic: pl.DataFrame) -> pl.DataFrame:
    """Return finite log size only for positive market capitalization."""
    keys = ["symbol", "trade_date"]
    if basic.select(pl.struct(keys).is_duplicated().any()).item():
        raise ValueError("Duplicate daily market size")
    return basic.select(*keys, pl.when(
        pl.col("total_market_value").is_finite() & (pl.col("total_market_value") > 0)
    ).then(pl.col("total_market_value").log()).otherwise(None).alias("log_total_market_value"))
