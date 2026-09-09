"""Trailing gross margin from PIT-selected cumulative income statements."""

import polars as pl

from quant.factors.pit_quality import _single_quarters


def compute_gross_margin(income: pl.DataFrame) -> pl.DataFrame:
    """Require four consecutive quarters, positive sales and nonnegative costs."""
    groups = ["symbol", "report_type", "comp_type"]
    keys = [*groups, "end_date"]
    if income.select(pl.struct(keys).is_duplicated().any()).item():
        raise ValueError("Duplicate PIT statement period")
    q = _single_quarters(income, ["revenue", "oper_cost"]).with_columns(
        pl.col("_single_revenue").rolling_sum(4, min_samples=4).over(groups).alias("revenue_ttm"),
        pl.col("_single_oper_cost").rolling_sum(4, min_samples=4).over(groups).alias("oper_cost_ttm"),
        (pl.col("_quarter_index") - pl.col("_quarter_index").shift(3).over(groups) == 3)
        .alias("_consecutive"),
    ).with_columns(
        pl.when(pl.col("_consecutive") & (pl.col("revenue_ttm") > 0)
                & (pl.col("oper_cost_ttm") >= 0)
                & pl.col("revenue_ttm").is_finite() & pl.col("oper_cost_ttm").is_finite())
        .then((pl.col("revenue_ttm") - pl.col("oper_cost_ttm")) / pl.col("revenue_ttm"))
        .otherwise(None).alias("pit_gross_margin_ttm")
    )
    return q.select(*keys, "revenue_ttm", "oper_cost_ttm", "pit_gross_margin_ttm")
