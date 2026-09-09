"""Change in single-quarter year-on-year parent profit growth."""

import polars as pl

from quant.factors.pit_quality import _single_quarters


def compute_profit_acceleration(income: pl.DataFrame) -> pl.DataFrame:
    """Use six consecutive single quarters and sign-correct loss growth."""
    groups = ["symbol", "report_type", "comp_type"]
    keys = [*groups, "end_date"]
    if income.select(pl.struct(keys).is_duplicated().any()).item():
        raise ValueError("Duplicate PIT statement period")
    q = _single_quarters(income, ["n_income_attr_p"]).rename(
        {"_single_n_income_attr_p": "parent_profit_q"})
    q = q.with_columns(
        pl.col("parent_profit_q").shift(4).over(groups).alias("_prior"),
        (pl.col("_quarter_index") - pl.col("_quarter_index").shift(5).over(groups) == 5)
        .alias("_consecutive"),
        pl.col("parent_profit_q").is_finite().fill_null(False).cast(pl.Int32)
        .rolling_sum(6, min_samples=6).over(groups).alias("_finite_count"),
    ).with_columns(
        pl.when(pl.col("_prior") != 0)
        .then((pl.col("parent_profit_q") - pl.col("_prior")) / pl.col("_prior").abs())
        .otherwise(None).alias("growth_q"),
    ).with_columns(pl.col("growth_q").shift(1).over(groups).alias("growth_q_lag1"))
    q = q.with_columns(
        pl.when(pl.col("_consecutive") & (pl.col("_finite_count") == 6)
                & pl.col("growth_q").is_finite() & pl.col("growth_q_lag1").is_finite())
        .then(pl.col("growth_q") - pl.col("growth_q_lag1"))
        .otherwise(None).alias("pit_profit_acceleration"),
    )
    q = q.with_columns(pl.when(pl.col("pit_profit_acceleration").is_finite())
        .then(pl.col("pit_profit_acceleration")).otherwise(None).alias("pit_profit_acceleration"))
    return q.select(*keys, "parent_profit_q", "growth_q", "growth_q_lag1", "pit_profit_acceleration")
