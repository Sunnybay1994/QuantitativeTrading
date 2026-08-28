"""Sixth-batch Alpha101 price-volume geometry factors for M2 research."""

from __future__ import annotations

import datetime as dt

import polars as pl

from quant.domain import Bar1dSchema
from quant.factors.classic import ClassicFactorSpec


SIXTH_BATCH_FACTOR_SPECS: tuple[ClassicFactorSpec, ...] = (
    ClassicFactorSpec(
        "alpha101_006",
        "Alpha101 #6: -Corr(adjusted_open, raw_volume, 10 strict exchange sessions)",
        "ten-session adjusted-open and raw-volume correlation",
    ),
    ClassicFactorSpec(
        "alpha101_012",
        "Alpha101 #12: Sign(Delta(raw_volume, 1)) * -Delta(adjusted_close, 1)",
        "one-session raw-volume direction and adjusted-price change",
    ),
    ClassicFactorSpec(
        "alpha101_041",
        "Alpha101 #41: sqrt(raw_high * raw_low) - amount / volume",
        "raw-price geometric mean versus raw VWAP",
    ),
)

SIXTH_BATCH_FACTOR_NAMES = tuple(spec.name for spec in SIXTH_BATCH_FACTOR_SPECS)

_CORRELATION_WINDOW = 10
_DELTA_LAG = 1
_NUMERIC_SOURCE_COLUMNS = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "adj_factor",
)


def compute_sixth_batch_daily_factors(
    bars: pl.DataFrame,
    *,
    sessions: tuple[dt.date, ...],
) -> pl.DataFrame:
    """Compute the three frozen Alpha101 price-volume candidates.

    A complete symbol-by-session grid is used for rolling and lagged
    calculations. Missing bars therefore invalidate only the affected
    window or pair and are never silently bridged.
    """
    if (
        not isinstance(bars, pl.DataFrame)
        or bars.is_empty()
        or type(sessions) is not tuple
        or not sessions
        or any(type(value) is not dt.date for value in sessions)
        or sessions != tuple(sorted(set(sessions)))
    ):
        raise ValueError("invalid sixth-batch factor request")

    if any(
        bars.schema.get(column) == pl.Boolean
        for column in _NUMERIC_SOURCE_COLUMNS
        if column in bars.columns
    ):
        raise ValueError("sixth-batch bars contain boolean numeric sources")

    try:
        clean = Bar1dSchema.validate(bars).sort(
            "symbol", "trade_date", "source"
        )
    except Exception as exc:
        raise ValueError("sixth-batch bars fail Bar1dSchema validation") from exc

    if clean.select(pl.struct("symbol", "trade_date").is_duplicated().any()).item():
        raise ValueError("sixth-batch bars must have one source per symbol-date")
    session_set = set(sessions)
    if any(value not in session_set for value in clean.get_column("trade_date")):
        raise ValueError("sixth-batch bars contain dates outside the session calendar")
    if _has_non_finite(clean, _NUMERIC_SOURCE_COLUMNS):
        raise ValueError("sixth-batch bars contain non-finite numeric sources")

    prepared = clean.with_columns(
        (pl.col("open") * pl.col("adj_factor")).alias("_adjusted_open"),
        (pl.col("close") * pl.col("adj_factor")).alias("_adjusted_close"),
        (pl.col("high") * pl.col("low")).alias("_raw_high_low"),
    )
    if _has_non_finite(
        prepared,
        ("_adjusted_open", "_adjusted_close", "_raw_high_low"),
    ):
        raise ValueError("sixth-batch factor arithmetic is non-finite")

    session_frame = pl.DataFrame(
        {"trade_date": sessions},
        schema={"trade_date": pl.Date},
    )
    symbols = clean.select("symbol").unique().sort("symbol")
    keys = clean.select("symbol", "trade_date").sort("symbol", "trade_date")
    grid = (
        symbols.join(session_frame, how="cross")
        .join(
            prepared.select(
                "symbol",
                "trade_date",
                "volume",
                "amount",
                "high",
                "low",
                "_adjusted_open",
                "_adjusted_close",
                "_raw_high_low",
            ),
            on=["symbol", "trade_date"],
            how="left",
            validate="1:1",
        )
        .sort("symbol", "trade_date")
        .with_columns(
            _strictly_positive("_adjusted_open").alias("_alpha006_open"),
            _strictly_positive("volume").alias("_alpha006_volume"),
            _strictly_positive("_adjusted_close").alias("_alpha012_close"),
            _strictly_positive("volume").alias("_alpha012_volume"),
            pl.when(
                pl.col("_raw_high_low").is_not_null()
                & pl.col("_raw_high_low").is_finite()
                & (pl.col("high") > 0)
                & (pl.col("low") > 0)
            )
            .then(pl.col("_raw_high_low"))
            .otherwise(pl.lit(None, dtype=pl.Float64))
            .alias("_alpha041_product"),
            pl.when(
                pl.col("amount").is_not_null()
                & pl.col("amount").is_finite()
                & (pl.col("amount") > 0)
                & pl.col("volume").is_not_null()
                & pl.col("volume").is_finite()
                & (pl.col("volume") > 0)
            )
            .then(pl.col("amount") / pl.col("volume"))
            .otherwise(pl.lit(None, dtype=pl.Float64))
            .alias("_alpha041_vwap"),
        )
        .with_columns(
            pl.col("_alpha006_open")
            .is_not_null()
            .cast(pl.Int64)
            .rolling_sum(
                _CORRELATION_WINDOW,
                min_samples=_CORRELATION_WINDOW,
            )
            .over("symbol")
            .alias("_alpha006_open_count"),
            pl.col("_alpha006_volume")
            .is_not_null()
            .cast(pl.Int64)
            .rolling_sum(
                _CORRELATION_WINDOW,
                min_samples=_CORRELATION_WINDOW,
            )
            .over("symbol")
            .alias("_alpha006_volume_count"),
            pl.rolling_corr(
                pl.col("_alpha006_open"),
                pl.col("_alpha006_volume"),
                window_size=_CORRELATION_WINDOW,
                min_samples=_CORRELATION_WINDOW,
                ddof=1,
            )
            .over("symbol")
            .alias("_alpha006_corr"),
            (
                pl.col("_alpha012_volume")
                - pl.col("_alpha012_volume").shift(_DELTA_LAG).over("symbol")
            ).alias("_alpha012_volume_delta"),
            (
                pl.col("_alpha012_close")
                - pl.col("_alpha012_close").shift(_DELTA_LAG).over("symbol")
            ).alias("_alpha012_close_delta"),
            pl.col("_alpha041_product")
            .sqrt()
            .alias("_alpha041_geometric_mean"),
        )
    )

    if _has_non_finite(
        grid,
        ("_alpha041_vwap", "_alpha041_geometric_mean"),
        non_null_only=True,
    ) or _has_non_finite(
        grid,
        ("_alpha012_volume_delta", "_alpha012_close_delta"),
        non_null_only=True,
    ):
        raise ValueError("sixth-batch factor arithmetic is non-finite")

    grid = grid.with_columns(
        pl.when(
            (pl.col("_alpha006_open_count") == _CORRELATION_WINDOW)
            & (pl.col("_alpha006_volume_count") == _CORRELATION_WINDOW)
            & pl.col("_alpha006_corr").is_not_null()
            & pl.col("_alpha006_corr").is_finite()
        )
        .then(-pl.col("_alpha006_corr"))
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .cast(pl.Float64)
        .alias("alpha101_006"),
        pl.when(
            pl.col("_alpha012_volume_delta").is_not_null()
            & pl.col("_alpha012_close_delta").is_not_null()
        )
        .then(
            pl.when(pl.col("_alpha012_volume_delta") > 0)
            .then(-pl.col("_alpha012_close_delta"))
            .when(pl.col("_alpha012_volume_delta") < 0)
            .then(pl.col("_alpha012_close_delta"))
            .otherwise(pl.lit(0.0))
        )
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .cast(pl.Float64)
        .alias("alpha101_012"),
        (
            pl.col("_alpha041_geometric_mean") - pl.col("_alpha041_vwap")
        )
        .cast(pl.Float64)
        .alias("alpha101_041"),
    )

    result = (
        keys.join(
            grid.select("symbol", "trade_date", *SIXTH_BATCH_FACTOR_NAMES),
            on=["symbol", "trade_date"],
            how="left",
            validate="1:1",
        )
        .select(
            "symbol",
            "trade_date",
            *[
                pl.col(name).cast(pl.Float64).alias(name)
                for name in SIXTH_BATCH_FACTOR_NAMES
            ],
        )
        .sort("symbol", "trade_date")
    )
    if _has_non_finite(
        result,
        SIXTH_BATCH_FACTOR_NAMES,
        non_null_only=True,
    ):
        raise ValueError("sixth-batch factors contain non-finite values")
    return result


def _strictly_positive(column: str) -> pl.Expr:
    value = pl.col(column)
    return (
        pl.when(
            value.is_not_null()
            & value.is_finite()
            & (value > 0)
        )
        .then(value)
        .otherwise(pl.lit(None, dtype=pl.Float64))
    )


def _has_non_finite(
    frame: pl.DataFrame,
    columns: tuple[str, ...],
    *,
    non_null_only: bool = False,
) -> bool:
    expressions: list[pl.Expr] = []
    for column in columns:
        expression = pl.col(column).is_finite()
        if non_null_only:
            expression = pl.col(column).is_not_null() & ~expression
        else:
            expression = ~expression
        expressions.append(expression)
    return bool(
        frame.select(pl.any_horizontal(*expressions).fill_null(False).any()).item()
    )


__all__ = [
    "SIXTH_BATCH_FACTOR_NAMES",
    "SIXTH_BATCH_FACTOR_SPECS",
    "compute_sixth_batch_daily_factors",
]
