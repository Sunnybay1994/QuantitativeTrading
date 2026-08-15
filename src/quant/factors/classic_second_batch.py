"""Second-batch non-redundant daily price/volume factors for M2 research."""

from __future__ import annotations

import polars as pl

from quant.domain import Bar1dSchema
from quant.factors.classic import ClassicFactorSpec

SECOND_BATCH_FACTOR_SPECS: tuple[ClassicFactorSpec, ...] = (
    ClassicFactorSpec(
        "alpha158_ma20",
        "Alpha158 MA20: Mean(adj_close,20)/adj_close",
        "twenty-session moving-average deviation and redundancy probe",
    ),
    ClassicFactorSpec(
        "alpha158_corr20",
        "Alpha158 CORR20: Corr(adj_close,Log(volume+1),20)",
        "twenty-session price-volume level correlation",
    ),
    ClassicFactorSpec(
        "alpha158_wvma20",
        "Alpha158 WVMA20: Std(abs(ret)*volume,20)/(Mean(abs(ret)*volume,20)+1e-12)",
        "volume-weighted absolute-return instability",
    ),
)

SECOND_BATCH_FACTOR_NAMES = tuple(spec.name for spec in SECOND_BATCH_FACTOR_SPECS)


def compute_second_batch_daily_factors(bars: pl.DataFrame) -> pl.DataFrame:
    """Compute the frozen MA20, CORR20 and WVMA20 catalog."""
    if not isinstance(bars, pl.DataFrame) or bars.is_empty():
        raise ValueError("second-batch factor bars must be non-empty")
    clean = Bar1dSchema.validate(bars).sort("symbol", "trade_date", "source")
    if clean.select(pl.struct("symbol", "trade_date").is_duplicated().any()).item():
        raise ValueError("second-batch bars must have one source per symbol-date")
    prepared = clean.with_columns(
        (pl.col("close") * pl.col("adj_factor")).alias("_adj_close"),
        pl.col("volume").log1p().alias("_log_volume"),
        pl.col("trade_date").cum_count().over("symbol").alias("history_rows"),
        pl.col("amount").rolling_mean(window_size=20).over("symbol").alias(
            "liquidity_20"
        ),
    ).with_columns(
        (
            (
                pl.col("_adj_close")
                / pl.col("_adj_close").shift(1).over("symbol")
                - 1.0
            ).abs()
            * pl.col("volume")
        ).alias("_weighted_abs_return")
    )
    result = prepared.with_columns(
        (
            pl.col("_adj_close").rolling_mean(window_size=20).over("symbol")
            / pl.col("_adj_close")
        ).alias("alpha158_ma20"),
        pl.rolling_corr(
            pl.col("_adj_close"),
            pl.col("_log_volume"),
            window_size=20,
            min_samples=20,
            ddof=1,
        )
        .over("symbol")
        .alias("alpha158_corr20"),
        (
            pl.col("_weighted_abs_return")
            .rolling_std(window_size=20, ddof=1)
            .over("symbol")
            / (
                pl.col("_weighted_abs_return")
                .rolling_mean(window_size=20)
                .over("symbol")
                + 1e-12
            )
        ).alias("alpha158_wvma20"),
    ).drop("_adj_close", "_log_volume", "_weighted_abs_return")
    if result.select(
        pl.any_horizontal(
            *[pl.col(name).is_infinite() for name in SECOND_BATCH_FACTOR_NAMES]
        ).any()
    ).item():
        raise ValueError("second-batch factors contain infinite values")
    return result


__all__ = [
    "SECOND_BATCH_FACTOR_NAMES",
    "SECOND_BATCH_FACTOR_SPECS",
    "compute_second_batch_daily_factors",
]
