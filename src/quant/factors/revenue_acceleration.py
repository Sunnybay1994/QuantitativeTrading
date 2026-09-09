"""Change in single-quarter year-on-year revenue growth."""

import polars as pl

from quant.factors.pit_quality import _single_quarters


def compute_revenue_acceleration(income: pl.DataFrame) -> pl.DataFrame:
    """Use six consecutive single quarters with nonnegative revenue."""
    groups = ["symbol", "report_type", "comp_type"]
    keys = [*groups, "end_date"]
    if income.select(pl.struct(keys).is_duplicated().any()).item():
        raise ValueError("Duplicate PIT statement period")
    q = _single_quarters(income, ["revenue"]).rename(
        {"_single_revenue": "revenue_q"})
    q = q.with_columns(
        pl.col("revenue_q").shift(4).over(groups).alias("_prior"),
        (pl.col("_quarter_index") - pl.col("_quarter_index").shift(5).over(groups) == 5)
        .alias("_consecutive"),
        (pl.col("revenue_q").is_finite() & (pl.col("revenue_q") >= 0)).fill_null(False).cast(pl.Int32)
        .rolling_sum(6, min_samples=6).over(groups).alias("_finite_count"),
    ).with_columns(
        pl.when(pl.col("_prior") > 0)
        .then((pl.col("revenue_q") - pl.col("_prior")) / pl.col("_prior"))
        .otherwise(None).alias("growth_q"),
    ).with_columns(pl.col("growth_q").shift(1).over(groups).alias("growth_q_lag1"))
    q = q.with_columns(
        pl.when(pl.col("_consecutive") & (pl.col("_finite_count") == 6)
                & pl.col("growth_q").is_finite() & pl.col("growth_q_lag1").is_finite())
        .then(pl.col("growth_q") - pl.col("growth_q_lag1"))
        .otherwise(None).alias("pit_revenue_acceleration"),
    )
    q = q.with_columns(pl.when(pl.col("pit_revenue_acceleration").is_finite())
        .then(pl.col("pit_revenue_acceleration")).otherwise(None).alias("pit_revenue_acceleration"))
    return q.select(*keys, "revenue_q", "growth_q", "growth_q_lag1", "pit_revenue_acceleration")
