"""Three fixed financial ratios from already selected point-in-time statements."""

import polars as pl

from quant.factors.pit_quality import _single_quarters, _quarter_coordinates
from quant.factors.cash_yield import compute_ocf_ttm


GROUPS = ["symbol", "report_type", "comp_type"]
KEYS = [*GROUPS, "end_date"]


def _ttm(income: pl.DataFrame, columns: tuple[str, ...]) -> pl.DataFrame:
    if income.select(pl.struct(KEYS).is_duplicated().any()).item():
        raise ValueError("Duplicate PIT income periods")
    quarters = _single_quarters(income, list(columns)).with_columns(
        (pl.col("_quarter_index") - pl.col("_quarter_index").shift(3).over(GROUPS) == 3).alias("_complete"),
        *[pl.col(f"_single_{name}").rolling_sum(4, min_samples=4).over(GROUPS).alias(f"{name}_ttm")
          for name in columns],
    )
    return quarters.select(*KEYS, "_quarter_index",
        *[pl.when(pl.col("_complete") & pl.col(f"{name}_ttm").is_finite())
          .then(pl.col(f"{name}_ttm")).otherwise(None).alias(f"{name}_ttm") for name in columns])


def compute_net_margin(income: pl.DataFrame) -> pl.DataFrame:
    frame = _ttm(income, ("n_income", "revenue"))
    value = pl.col("n_income_ttm") / pl.col("revenue_ttm")
    return frame.with_columns(pl.when((pl.col("revenue_ttm") > 0) & value.is_finite())
        .then(value).otherwise(None).alias("pit_net_margin_ttm"))


def compute_asset_turnover(income: pl.DataFrame, balance: pl.DataFrame) -> pl.DataFrame:
    if balance.select(pl.struct(KEYS).is_duplicated().any()).item():
        raise ValueError("Duplicate PIT balance periods")
    lag = _quarter_coordinates(balance).select(*GROUPS,
        (pl.col("_quarter_index") + 4).alias("_quarter_index"), pl.col("total_assets").alias("prior_assets"))
    frame = _ttm(income, ("revenue",)).join(balance.select(*KEYS, "total_assets"),
        on=KEYS, how="left", validate="1:1").join(lag, on=[*GROUPS, "_quarter_index"], how="left", validate="1:1")
    value = pl.col("revenue_ttm") / ((pl.col("total_assets") + pl.col("prior_assets")) / 2)
    valid = ((pl.col("revenue_ttm") >= 0) & (pl.col("total_assets") > 0) & (pl.col("prior_assets") > 0)
             & pl.col("total_assets").is_finite() & pl.col("prior_assets").is_finite() & value.is_finite())
    return frame.with_columns(pl.when(valid).then(value).otherwise(None).alias("pit_asset_turnover_ttm"))


def compute_cash_to_liabilities(cash: pl.DataFrame, balance: pl.DataFrame) -> pl.DataFrame:
    if balance.select(pl.struct(KEYS).is_duplicated().any()).item():
        raise ValueError("Duplicate PIT balance periods")
    frame = compute_ocf_ttm(cash).join(balance.select(*KEYS, "total_liab"), on=KEYS, how="left", validate="1:1")
    value = pl.col("ocf_ttm") / pl.col("total_liab")
    return frame.with_columns(pl.when((pl.col("total_liab") > 0) & pl.col("total_liab").is_finite() & value.is_finite())
        .then(value).otherwise(None).alias("pit_cash_to_liabilities_ttm"))
