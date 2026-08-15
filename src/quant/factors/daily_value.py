"""Low-assumption daily value proxies derived from PIT ``daily_basic`` snapshots."""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from quant.domain import DailyBasic1dSchema


@dataclass(frozen=True, slots=True)
class DailyValueFactorSpec:
    """Auditable formula and missing-value rule for one daily value proxy."""

    name: str
    source: str
    mechanism: str
    missing_rule: str


DAILY_VALUE_FACTOR_SPECS: tuple[DailyValueFactorSpec, ...] = (
    DailyValueFactorSpec(
        "daily_ep_ttm_positive",
        "daily_basic.pe_ttm: 1 / pe_ttm when pe_ttm > 0",
        "positive trailing earnings yield",
        "null for loss-making, zero, non-finite, or missing PE",
    ),
    DailyValueFactorSpec(
        "daily_bp_positive",
        "daily_basic.pb: 1 / pb when pb > 0",
        "positive book-to-price proxy",
        "null for non-positive, non-finite, or missing PB",
    ),
    DailyValueFactorSpec(
        "daily_sp_ttm_positive",
        "daily_basic.ps_ttm: 1 / ps_ttm when ps_ttm > 0",
        "positive trailing sales yield",
        "null for non-positive, non-finite, or missing PS",
    ),
    DailyValueFactorSpec(
        "daily_dividend_yield_ttm",
        "daily_basic.dv_ttm percent / 100",
        "trailing cash distribution yield",
        "preserve source null; zero is a valid no-dividend observation",
    ),
)

DAILY_VALUE_FACTOR_NAMES = tuple(spec.name for spec in DAILY_VALUE_FACTOR_SPECS)


def compute_daily_value_factors(daily_basic: pl.DataFrame) -> pl.DataFrame:
    """Compute frozen daily value proxies without filling or ranking source values."""
    if not isinstance(daily_basic, pl.DataFrame) or daily_basic.is_empty():
        raise ValueError("daily value factor input must be non-empty")
    clean = DailyBasic1dSchema.validate(daily_basic).sort(
        ["symbol", "trade_date", "source"]
    )
    result = clean.with_columns(
        pl.when(pl.col("pe_ttm") > 0)
        .then(1.0 / pl.col("pe_ttm"))
        .otherwise(None)
        .alias("daily_ep_ttm_positive"),
        pl.when(pl.col("pb") > 0)
        .then(1.0 / pl.col("pb"))
        .otherwise(None)
        .alias("daily_bp_positive"),
        pl.when(pl.col("ps_ttm") > 0)
        .then(1.0 / pl.col("ps_ttm"))
        .otherwise(None)
        .alias("daily_sp_ttm_positive"),
        (pl.col("dividend_yield_ttm") / 100.0).alias(
            "daily_dividend_yield_ttm"
        ),
        pl.col("total_market_value").log().alias("log_total_market_value"),
    )
    if result.select(
        pl.any_horizontal(
            *[pl.col(name).is_infinite() for name in DAILY_VALUE_FACTOR_NAMES],
            pl.col("log_total_market_value").is_infinite(),
        ).any()
    ).item():
        raise ValueError("daily value factors contain infinite values")
    return result


__all__ = [
    "DAILY_VALUE_FACTOR_NAMES",
    "DAILY_VALUE_FACTOR_SPECS",
    "DailyValueFactorSpec",
    "compute_daily_value_factors",
]
