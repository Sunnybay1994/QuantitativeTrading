"""Operating cash flow over average assets from PIT-selected statements."""

import polars as pl

from quant.factors.pit_quality import _quarter_coordinates, _single_quarters


def compute_cash_roa(cash: pl.DataFrame, balance: pl.DataFrame) -> pl.DataFrame:
    """Require four consecutive cash quarters and both matching asset endpoints."""
    groups = ["symbol", "report_type", "comp_type"]
    keys = [*groups, "end_date"]
    if any(f.select(pl.struct(keys).is_duplicated().any()).item() for f in (cash, balance)):
        raise ValueError("Duplicate PIT statement period")
    lag = _quarter_coordinates(balance).select(
        *groups, (pl.col("_quarter_index") + 4).alias("_quarter_index"),
        pl.col("total_assets").alias("prior_assets"),
    )
    q = _single_quarters(cash, ["n_cashflow_act"]).with_columns(
        pl.col("_single_n_cashflow_act").rolling_sum(4, min_samples=4).over(groups).alias("ocf_ttm"),
        (pl.col("_quarter_index") - pl.col("_quarter_index").shift(3).over(groups) == 3)
        .alias("_consecutive"),
    ).join(balance.select(*keys, "total_assets"), on=keys, how="left", validate="1:1").join(
        lag, on=[*groups, "_quarter_index"], how="left", validate="1:1",
    ).with_columns(((pl.col("total_assets") + pl.col("prior_assets")) / 2).alias("average_assets"))
    valid = pl.col("_consecutive") & pl.col("ocf_ttm").is_finite()
    for col in ("total_assets", "prior_assets", "average_assets"):
        valid = valid & pl.col(col).is_finite() & (pl.col(col) > 0)
    return q.with_columns(
        pl.when(valid).then(pl.col("ocf_ttm") / pl.col("average_assets"))
        .otherwise(None).alias("pit_cash_roa_ttm")
    ).select(*keys, "ocf_ttm", "total_assets", "prior_assets", "average_assets", "pit_cash_roa_ttm")
