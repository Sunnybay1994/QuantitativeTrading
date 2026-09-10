"""Operating cash-flow yield from PIT cash statements and same-day market value."""

import polars as pl

from quant.factors.pit_quality import _single_quarters


def compute_ocf_ttm(cash: pl.DataFrame) -> pl.DataFrame:
    """Keep negative cash flow; exclude missing quarters and nonfinite totals."""
    groups = ["symbol", "report_type", "comp_type"]
    keys = [*groups, "end_date"]
    if cash.select(pl.struct(keys).is_duplicated().any()).item():
        raise ValueError("Duplicate PIT statement period")
    q = _single_quarters(cash, ["n_cashflow_act"]).with_columns(
        pl.col("_single_n_cashflow_act").rolling_sum(4, min_samples=4).over(groups).alias("_sum"),
        (pl.col("_quarter_index") - pl.col("_quarter_index").shift(3).over(groups) == 3)
        .alias("_consecutive"),
    )
    return q.select(*keys, pl.when(pl.col("_consecutive") & pl.col("_sum").is_finite())
                    .then(pl.col("_sum")).otherwise(None).alias("ocf_ttm"))


def compute_cash_yield(financial: pl.DataFrame, daily_basic: pl.DataFrame) -> pl.DataFrame:
    """Both cash flow and clean total market value are in yuan; no forward fill."""
    keys = ["symbol", "trade_date"]
    joined = financial.join(daily_basic.select(*keys, "total_market_value"),
                            on=keys, how="left", validate="1:1")
    return joined.with_columns(
        pl.when(pl.col("ocf_ttm").is_finite() & pl.col("total_market_value").is_finite()
                & (pl.col("total_market_value") > 0))
        .then(pl.col("ocf_ttm") / pl.col("total_market_value"))
        .otherwise(None).alias("pit_cash_yield_ttm")
    )
