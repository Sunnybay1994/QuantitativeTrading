"""Annual growth of trailing revenue from PIT-selected income statements."""

import polars as pl

from quant.factors.pit_quality import _single_quarters


def compute_revenue_growth(income: pl.DataFrame) -> pl.DataFrame:
    """Compare consecutive four-quarter totals with the exact year-ago total."""
    groups = ["symbol", "report_type", "comp_type"]
    keys = [*groups, "end_date"]
    if income.select(pl.struct(keys).is_duplicated().any()).item():
        raise ValueError("Duplicate PIT statement period")
    q = _single_quarters(income, ["revenue"]).with_columns(
        pl.col("_single_revenue").rolling_sum(4, min_samples=4).over(groups).alias("_sum"),
        (pl.col("_quarter_index") - pl.col("_quarter_index").shift(3).over(groups) == 3)
        .alias("_consecutive"),
    ).with_columns(
        pl.when(pl.col("_consecutive") & pl.col("_sum").is_finite())
        .then(pl.col("_sum")).otherwise(None).alias("revenue_ttm"),
    ).with_columns(
        pl.col("revenue_ttm").shift(4).over(groups).alias("revenue_ttm_lag4"),
        (pl.col("_quarter_index") - pl.col("_quarter_index").shift(7).over(groups) == 7)
        .alias("_eight_quarters"),
    ).with_columns(
        pl.when(pl.col("_eight_quarters") & (pl.col("revenue_ttm") >= 0)
                & (pl.col("revenue_ttm_lag4") > 0))
        .then(pl.col("revenue_ttm") / pl.col("revenue_ttm_lag4") - 1)
        .otherwise(None).alias("pit_revenue_growth_ttm"),
    ).with_columns(
        pl.when(pl.col("pit_revenue_growth_ttm").is_finite())
        .then(pl.col("pit_revenue_growth_ttm")).otherwise(None).alias("pit_revenue_growth_ttm"),
    )
    return q.select(*keys, "revenue_ttm", "revenue_ttm_lag4", "pit_revenue_growth_ttm")
