"""Daily total or circulating market size without value or quality filters."""

import polars as pl


def compute_market_size(basic: pl.DataFrame, *, column: str = "total_market_value") -> pl.DataFrame:
    """Return finite log size only for positive market capitalization."""
    if column not in {"total_market_value", "circulating_market_value"}:
        raise ValueError("Unsupported market size column")
    keys = ["symbol", "trade_date"]
    if basic.select(pl.struct(keys).is_duplicated().any()).item():
        raise ValueError("Duplicate daily market size")
    return basic.select(*keys, pl.when(
        pl.col(column).is_finite() & (pl.col(column) > 0)
    ).then(pl.col(column).log()).otherwise(None).alias(f"log_{column}"))
