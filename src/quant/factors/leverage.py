"""Same-period liabilities to assets from PIT-selected balance sheets."""

import polars as pl


def compute_leverage(balance: pl.DataFrame) -> pl.DataFrame:
    """Keep ratios above one; exclude invalid assets and negative liabilities."""
    keys = ["symbol", "report_type", "comp_type", "end_date"]
    if balance.select(pl.struct(keys).is_duplicated().any()).item():
        raise ValueError("Duplicate PIT statement period")
    return balance.select(*keys, "total_assets", "total_liab",
        pl.when(pl.col("total_assets").is_finite() & (pl.col("total_assets") > 0)
                & pl.col("total_liab").is_finite() & (pl.col("total_liab") >= 0))
        .then(pl.col("total_liab") / pl.col("total_assets"))
        .otherwise(None).alias("pit_liabilities_to_assets"),
    ).with_columns(pl.when(pl.col("pit_liabilities_to_assets").is_finite())
        .then(pl.col("pit_liabilities_to_assets")).otherwise(None).alias("pit_liabilities_to_assets"))
