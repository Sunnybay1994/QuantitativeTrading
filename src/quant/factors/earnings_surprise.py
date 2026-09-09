"""Seasonal earnings surprise from already selected PIT cumulative income."""

import polars as pl

from quant.factors.pit_quality import _single_quarters


def compute_sue8(income: pl.DataFrame) -> pl.DataFrame:
    """Standardize current seasonal change by the preceding eight changes."""
    groups = ["symbol", "report_type", "comp_type"]
    keys = [*groups, "end_date"]
    if income.select(pl.struct(keys).is_duplicated().any()).item():
        raise ValueError("Duplicate PIT income periods")
    q = _single_quarters(income, ["n_income_attr_p"])
    lagged = q.select(
        *groups, (pl.col("_quarter_index") + 4).alias("_quarter_index"),
        pl.col("_single_n_income_attr_p").alias("_lag4"),
    )
    q = q.join(lagged, on=[*groups, "_quarter_index"], how="left", validate="1:1").sort(
        [*groups, "_quarter_index"]
    ).with_columns((pl.col("_single_n_income_attr_p") - pl.col("_lag4")).alias("_delta"))
    q = q.with_columns(pl.col("_delta").shift(1).over(groups).alias("_past"))
    q = q.with_columns(
        pl.col("_past").rolling_mean(8, min_samples=8).over(groups).alias("_mean"),
        pl.col("_past").rolling_std(8, min_samples=8, ddof=1).over(groups).alias("_std"),
        (pl.col("_quarter_index") - pl.col("_quarter_index").shift(8).over(groups) == 8)
        .alias("_consecutive"),
    ).with_columns(
        pl.when(pl.col("_consecutive") & (pl.col("_std") > 0))
        .then((pl.col("_delta") - pl.col("_mean")) / pl.col("_std"))
        .otherwise(None).alias("pit_sue8")
    )
    return q.select(*keys, "_single_n_income_attr_p", "_delta", "_mean", "_std", "pit_sue8")
