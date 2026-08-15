"""De-duplicated classic daily price/volume factors for M2 research."""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from quant.domain import Bar1dSchema


@dataclass(frozen=True, slots=True)
class ClassicFactorSpec:
    """Auditable identity and source formula for one canonical factor."""

    name: str
    source: str
    mechanism: str
    aliases: tuple[str, ...] = ()


CLASSIC_FACTOR_SPECS: tuple[ClassicFactorSpec, ...] = (
    ClassicFactorSpec(
        "alpha101_033",
        "Alpha101 #33: 1-open/close",
        "intraday reversal",
        ("alpha158_open0_inverse",),
    ),
    ClassicFactorSpec(
        "alpha101_101",
        "Alpha101 #101: (close-open)/(high-low+0.001)",
        "close location within the daily range",
        ("alpha158_kmid2_near_duplicate",),
    ),
    ClassicFactorSpec(
        "alpha158_roc20",
        "Alpha158 ROC20: Ref(adj_close,20)/adj_close",
        "twenty-session reversal",
    ),
    ClassicFactorSpec(
        "alpha158_std20",
        "Alpha158 STD20: Std(adj_close,20)/adj_close",
        "price dispersion",
    ),
    ClassicFactorSpec(
        "alpha158_rsv20",
        "Alpha158 RSV20: (adj_close-Min(adj_low,20))/(Max(adj_high,20)-Min(adj_low,20)+1e-12)",
        "twenty-session range position",
    ),
    ClassicFactorSpec(
        "alpha158_vma20",
        "Alpha158 VMA20: Mean(volume,20)/volume",
        "relative volume",
    ),
)

CLASSIC_FACTOR_NAMES = tuple(spec.name for spec in CLASSIC_FACTOR_SPECS)


def compute_classic_daily_factors(bars: pl.DataFrame) -> pl.DataFrame:
    """Compute the frozen six-factor catalog from validated clean daily bars."""
    if not isinstance(bars, pl.DataFrame) or bars.is_empty():
        raise ValueError("classic factor bars must be non-empty")
    clean = Bar1dSchema.validate(bars).sort("symbol", "trade_date", "source")
    if clean.select(pl.struct("symbol", "trade_date").is_duplicated().any()).item():
        raise ValueError("classic factor bars must have one source per symbol-date")
    adjusted = clean.with_columns(
        (pl.col("high") * pl.col("adj_factor")).alias("_adj_high"),
        (pl.col("low") * pl.col("adj_factor")).alias("_adj_low"),
        (pl.col("close") * pl.col("adj_factor")).alias("_adj_close"),
        pl.col("trade_date").cum_count().over("symbol").alias("history_rows"),
    )
    low20 = pl.col("_adj_low").rolling_min(window_size=20).over("symbol")
    high20 = pl.col("_adj_high").rolling_max(window_size=20).over("symbol")
    result = adjusted.with_columns(
        (1.0 - pl.col("open") / pl.col("close")).alias("alpha101_033"),
        (
            (pl.col("close") - pl.col("open"))
            / (pl.col("high") - pl.col("low") + 0.001)
        ).alias("alpha101_101"),
        (
            pl.col("_adj_close").shift(20).over("symbol")
            / pl.col("_adj_close")
        ).alias("alpha158_roc20"),
        (
            pl.col("_adj_close")
            .rolling_std(window_size=20, ddof=1)
            .over("symbol")
            / pl.col("_adj_close")
        ).alias("alpha158_std20"),
        ((pl.col("_adj_close") - low20) / (high20 - low20 + 1e-12)).alias(
            "alpha158_rsv20"
        ),
        (
            pl.col("volume").rolling_mean(window_size=20).over("symbol")
            / pl.when(pl.col("volume") > 0).then(pl.col("volume")).otherwise(None)
        ).alias("alpha158_vma20"),
        pl.col("amount").rolling_mean(window_size=20).over("symbol").alias(
            "liquidity_20"
        ),
    ).drop("_adj_high", "_adj_low", "_adj_close")
    if result.select(
        pl.any_horizontal(
            *[pl.col(name).is_infinite() for name in CLASSIC_FACTOR_NAMES]
        ).any()
    ).item():
        raise ValueError("classic factors contain infinite values")
    return result


__all__ = [
    "CLASSIC_FACTOR_NAMES",
    "CLASSIC_FACTOR_SPECS",
    "ClassicFactorSpec",
    "compute_classic_daily_factors",
]
