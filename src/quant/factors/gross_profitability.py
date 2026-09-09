"""Trailing gross profit over matching-period assets, using PIT-selected inputs."""

import polars as pl

from quant.factors.pit_quality import _single_quarters


def compute_gross_profitability(income: pl.DataFrame, balance: pl.DataFrame) -> pl.DataFrame:
    """Require four consecutive single quarters and a matching balance sheet."""
    groups = ["symbol", "report_type", "comp_type"]
    keys = [*groups, "end_date"]
    if any(f.select(pl.struct(keys).is_duplicated().any()).item() for f in (income, balance)):
        raise ValueError("Duplicate PIT statement period")
    q = _single_quarters(income, ["revenue", "oper_cost"]).with_columns(
        pl.col("_single_revenue").rolling_sum(4, min_samples=4).over(groups).alias("revenue_ttm"),
        pl.col("_single_oper_cost").rolling_sum(4, min_samples=4).over(groups).alias("oper_cost_ttm"),
        (pl.col("_quarter_index") - pl.col("_quarter_index").shift(3).over(groups) == 3)
        .alias("_consecutive"),
    ).join(balance.select(*keys, "total_assets"), on=keys, how="left", validate="1:1")
    q = q.with_columns(
        pl.when(pl.col("_consecutive") & (pl.col("total_assets") > 0)
                & (pl.col("revenue_ttm") >= 0) & (pl.col("oper_cost_ttm") >= 0))
        .then((pl.col("revenue_ttm") - pl.col("oper_cost_ttm")) / pl.col("total_assets"))
        .otherwise(None).alias("pit_gross_profitability_ttm")
    )
    return q.select(*keys, "revenue_ttm", "oper_cost_ttm", "total_assets", "pit_gross_profitability_ttm")
