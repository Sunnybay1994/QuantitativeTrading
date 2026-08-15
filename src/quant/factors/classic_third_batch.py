"""Third-batch trend-quality and return-volume daily factors for M2."""

from __future__ import annotations

import polars as pl

from quant.domain import Bar1dSchema
from quant.factors.classic import ClassicFactorSpec

THIRD_BATCH_FACTOR_SPECS: tuple[ClassicFactorSpec, ...] = (
    ClassicFactorSpec(
        "alpha158_beta20",
        "Alpha158 BETA20: Slope(adj_close,20)/adj_close",
        "twenty-session normalized linear trend slope",
    ),
    ClassicFactorSpec(
        "alpha158_rsqr20",
        "Alpha158 RSQR20: Rsquare(adj_close,20)",
        "twenty-session linear-trend fit quality",
    ),
    ClassicFactorSpec(
        "alpha158_cord20",
        "Alpha158 CORD20: Corr(adj_close/Ref(adj_close,1),Log(volume/Ref(volume,1)+1),20)",
        "twenty-session return-ratio and volume-change correlation",
    ),
    ClassicFactorSpec(
        "alpha158_sumd20",
        "Alpha158 SUMD20: signed adj-close change sum / absolute adj-close change sum",
        "twenty-session directional price-change amplitude imbalance",
    ),
)

THIRD_BATCH_FACTOR_NAMES = tuple(spec.name for spec in THIRD_BATCH_FACTOR_SPECS)

_WINDOW = 20
_X_SUM = 190.0
_X_SQUARED_SUM = 2470.0
_X_DENOMINATOR = _WINDOW * _X_SQUARED_SUM - _X_SUM * _X_SUM
_X_WEIGHTS = [float(value) for value in range(_WINDOW)]


def compute_third_batch_daily_factors(bars: pl.DataFrame) -> pl.DataFrame:
    """Compute the frozen BETA20, RSQR20, CORD20 and SUMD20 catalog."""
    if not isinstance(bars, pl.DataFrame) or bars.is_empty():
        raise ValueError("third-batch factor bars must be non-empty")
    clean = Bar1dSchema.validate(bars).sort("symbol", "trade_date", "source")
    if clean.select(pl.struct("symbol", "trade_date").is_duplicated().any()).item():
        raise ValueError("third-batch bars must have one source per symbol-date")
    prepared = clean.with_columns(
        (pl.col("close") * pl.col("adj_factor")).alias("_adj_close"),
        pl.col("trade_date").cum_count().over("symbol").alias("history_rows"),
        pl.col("amount").rolling_mean(window_size=20).over("symbol").alias(
            "liquidity_20"
        ),
    ).with_columns(
        pl.col("_adj_close").diff().over("symbol").alias("_price_change"),
        (
            pl.col("_adj_close")
            / pl.col("_adj_close").shift(1).over("symbol")
        ).alias("_price_ratio"),
        pl.when(pl.col("volume").shift(1).over("symbol") > 0)
        .then(
            (
                pl.col("volume")
                / pl.col("volume").shift(1).over("symbol")
                + 1.0
            ).log()
        )
        .otherwise(None)
        .alias("_log_volume_ratio"),
    )
    sum_y = pl.col("_adj_close").rolling_sum(_WINDOW).over("symbol")
    sum_y_squared = (
        pl.col("_adj_close").pow(2).rolling_sum(_WINDOW).over("symbol")
    )
    sum_xy = (
        pl.col("_adj_close")
        .rolling_sum(_WINDOW, weights=_X_WEIGHTS)
        .over("symbol")
    )
    numerator = _WINDOW * sum_xy - _X_SUM * sum_y
    y_denominator = _WINDOW * sum_y_squared - sum_y.pow(2)
    result = prepared.with_columns(
        (
            (numerator / _X_DENOMINATOR)
            / pl.col("_adj_close")
        ).alias("alpha158_beta20"),
        pl.when(y_denominator > 0)
        .then(numerator.pow(2) / (_X_DENOMINATOR * y_denominator))
        .otherwise(None)
        .alias("alpha158_rsqr20"),
        pl.rolling_corr(
            pl.col("_price_ratio"),
            pl.col("_log_volume_ratio"),
            window_size=_WINDOW,
            min_samples=_WINDOW,
            ddof=1,
        )
        .over("symbol")
        .alias("alpha158_cord20"),
        (
            (
                pl.col("_price_change").clip(lower_bound=0).rolling_sum(_WINDOW)
                - (-pl.col("_price_change"))
                .clip(lower_bound=0)
                .rolling_sum(_WINDOW)
            ).over("symbol")
            / (
                pl.col("_price_change")
                .abs()
                .rolling_sum(_WINDOW)
                .over("symbol")
                + 1e-12
            )
        ).alias("alpha158_sumd20"),
    ).drop(
        "_adj_close",
        "_price_change",
        "_price_ratio",
        "_log_volume_ratio",
    )
    if result.select(
        pl.any_horizontal(
            *[pl.col(name).is_infinite() for name in THIRD_BATCH_FACTOR_NAMES]
        ).any()
    ).item():
        raise ValueError("third-batch factors contain infinite values")
    return result


__all__ = [
    "THIRD_BATCH_FACTOR_NAMES",
    "THIRD_BATCH_FACTOR_SPECS",
    "compute_third_batch_daily_factors",
]
