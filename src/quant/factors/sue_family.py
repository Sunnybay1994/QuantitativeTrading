"""SUE family variants for A4 (pre-registered; no Top-K / window rescue)."""
from __future__ import annotations

import datetime as dt
import math

import polars as pl

from quant.factors.pit_quality import _single_quarters

SUE_FAMILY_NAMES = (
    "sue_decay_tau20",
    "sue_decay_tau40",
    "sue_mad8",
    "rsue8",
    "sue_prelim",
)
SUE_FAMILY = "sue_family_v1"


def compute_sue_mad8(income: pl.DataFrame) -> pl.DataFrame:
    """SUE with 8-quarter MAD×1.4826 denominator (S2)."""
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
    # Rolling median absolute deviation of past deltas.
    q = q.with_columns(
        pl.col("_past").rolling_median(8, min_samples=8).over(groups).alias("_med"),
        pl.col("_past").rolling_mean(8, min_samples=8).over(groups).alias("_mean"),
        (pl.col("_quarter_index") - pl.col("_quarter_index").shift(8).over(groups) == 8)
        .alias("_consecutive"),
    ).with_columns(
        (pl.col("_past") - pl.col("_med")).abs().alias("_absdev"),
    ).with_columns(
        pl.col("_absdev").rolling_median(8, min_samples=8).over(groups).alias("_mad"),
    ).with_columns(
        pl.when(pl.col("_consecutive") & (pl.col("_mad") > 0))
        .then((pl.col("_delta") - pl.col("_mean")) / (pl.col("_mad") * 1.4826))
        .otherwise(None)
        .alias("sue_mad8")
    )
    return q.select(*keys, "sue_mad8")


def compute_rsue8(income: pl.DataFrame) -> pl.DataFrame:
    """Revenue surprise isomorphic to SUE (S3)."""
    groups = ["symbol", "report_type", "comp_type"]
    keys = [*groups, "end_date"]
    if "revenue" not in income.columns:
        raise ValueError("income history requires revenue for RSUE")
    if income.select(pl.struct(keys).is_duplicated().any()).item():
        raise ValueError("Duplicate PIT income periods")
    q = _single_quarters(income, ["revenue"])
    lagged = q.select(
        *groups, (pl.col("_quarter_index") + 4).alias("_quarter_index"),
        pl.col("_single_revenue").alias("_lag4"),
    )
    q = q.join(lagged, on=[*groups, "_quarter_index"], how="left", validate="1:1").sort(
        [*groups, "_quarter_index"]
    ).with_columns((pl.col("_single_revenue") - pl.col("_lag4")).alias("_delta"))
    q = q.with_columns(pl.col("_delta").shift(1).over(groups).alias("_past"))
    q = q.with_columns(
        pl.col("_past").rolling_mean(8, min_samples=8).over(groups).alias("_mean"),
        pl.col("_past").rolling_std(8, min_samples=8, ddof=1).over(groups).alias("_std"),
        (pl.col("_quarter_index") - pl.col("_quarter_index").shift(8).over(groups) == 8)
        .alias("_consecutive"),
    ).with_columns(
        pl.when(pl.col("_consecutive") & (pl.col("_std") > 0))
        .then((pl.col("_delta") - pl.col("_mean")) / pl.col("_std"))
        .otherwise(None)
        .alias("rsue8")
    )
    return q.select(*keys, "rsue8")


def apply_time_decay(
    sue: pl.DataFrame,
    *,
    signal_date: dt.date,
    available_date_col: str = "available_date",
    sue_col: str = "pit_sue8",
    taus: tuple[int, ...] = (20, 40),
) -> pl.DataFrame:
    """SUE × exp(-days/τ) with fixed τ (S1). Missing available_date → missing."""
    if sue_col not in sue.columns or available_date_col not in sue.columns:
        raise ValueError("decay requires SUE and available_date")
    out = sue.with_columns(
        pl.when(pl.col(available_date_col).is_not_null() & pl.col(sue_col).is_finite())
        .then((pl.lit(signal_date) - pl.col(available_date_col)).dt.total_days())
        .otherwise(None)
        .alias("_days")
    )
    for tau in taus:
        name = f"sue_decay_tau{tau}"
        out = out.with_columns(
            pl.when(pl.col("_days").is_not_null() & (pl.col("_days") >= 0))
            .then(pl.col(sue_col) * (-pl.col("_days").cast(pl.Float64) / float(tau)).exp())
            .otherwise(None)
            .alias(name)
        )
    return out.drop("_days")


def decay_scalar(sue: float, days: int, tau: int) -> float:
    if days < 0 or not math.isfinite(sue):
        raise ValueError("invalid decay inputs")
    return sue * math.exp(-days / tau)
