"""Same-period current assets to current liabilities from PIT-selected balance sheets."""

import polars as pl


def compute_current_ratio(balance: pl.DataFrame) -> pl.DataFrame:
    """Exclude nonpositive current liabilities and negative current assets."""
    keys = ["symbol", "report_type", "comp_type", "end_date"]
    if balance.select(pl.struct(keys).is_duplicated().any()).item():
        raise ValueError("Duplicate PIT statement period")
    return balance.select(*keys, "total_cur_liab", "total_cur_assets",
        pl.when(pl.col("total_cur_liab").is_finite() & (pl.col("total_cur_liab") > 0)
                & pl.col("total_cur_assets").is_finite() & (pl.col("total_cur_assets") >= 0))
        .then(pl.col("total_cur_assets") / pl.col("total_cur_liab"))
        .otherwise(None).alias("pit_current_ratio"),
    ).with_columns(pl.when(pl.col("pit_current_ratio").is_finite())
        .then(pl.col("pit_current_ratio")).otherwise(None).alias("pit_current_ratio"))
