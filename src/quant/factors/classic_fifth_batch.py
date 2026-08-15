"""Fifth-batch lottery-preference factor for M2 research."""

from __future__ import annotations

import datetime as dt

import polars as pl

from quant.domain import Bar1dSchema
from quant.factors.classic import ClassicFactorSpec

FIFTH_BATCH_FACTOR_SPECS: tuple[ClassicFactorSpec, ...] = (
    ClassicFactorSpec(
        "max_daily_return_20",
        "Bali-Cakici-Whitelaw MAX: maximum of twenty daily adjusted-close returns",
        "lottery-like extreme positive return and subsequent overpricing",
    ),
)

FIFTH_BATCH_FACTOR_NAMES = tuple(spec.name for spec in FIFTH_BATCH_FACTOR_SPECS)

_WINDOW = 20


def compute_fifth_batch_daily_factors(
    bars: pl.DataFrame,
    *,
    sessions: tuple[dt.date, ...],
) -> pl.DataFrame:
    """Compute MAX over twenty strict exchange-session simple returns.

    A value at session ``t`` requires adjusted closes for every session from
    ``t-20`` through ``t``. Missing observations invalidate the whole window;
    returns are never bridged across a gap.
    """
    if (
        not isinstance(bars, pl.DataFrame)
        or bars.is_empty()
        or type(sessions) is not tuple
        or not sessions
        or any(type(value) is not dt.date for value in sessions)
        or sessions != tuple(sorted(set(sessions)))
    ):
        raise ValueError("invalid fifth-batch factor request")

    clean = Bar1dSchema.validate(bars).sort("symbol", "trade_date", "source")
    if clean.select(pl.struct("symbol", "trade_date").is_duplicated().any()).item():
        raise ValueError("fifth-batch bars must have one source per symbol-date")
    session_set = set(sessions)
    if any(value not in session_set for value in clean.get_column("trade_date")):
        raise ValueError("fifth-batch bars contain dates outside the session calendar")
    if clean.select(
        (
            ~pl.col("close").is_finite()
            | ~pl.col("adj_factor").is_finite()
            | ~(pl.col("close") * pl.col("adj_factor")).is_finite()
        ).any()
    ).item():
        raise ValueError("fifth-batch bars contain non-finite adjusted closes")

    session_frame = pl.DataFrame(
        {"trade_date": sessions},
        schema={"trade_date": pl.Date},
    )
    symbols = clean.select("symbol").unique().sort("symbol")
    keys = clean.select("symbol", "trade_date").sort("symbol", "trade_date")
    grid = (
        symbols.join(session_frame, how="cross")
        .join(
            clean.select("symbol", "trade_date", "close", "adj_factor"),
            on=["symbol", "trade_date"],
            how="left",
            validate="1:1",
        )
        .sort("symbol", "trade_date")
        .with_columns((pl.col("close") * pl.col("adj_factor")).alias("_adj_close"))
        .with_columns(
            (
                pl.col("_adj_close")
                / pl.col("_adj_close").shift(1).over("symbol")
                - 1.0
            ).alias("_daily_return")
        )
    )
    if grid.filter(
        pl.col("_daily_return").is_not_null()
        & ~pl.col("_daily_return").is_finite()
    ).height:
        raise ValueError("fifth-batch returns contain non-finite values")

    grid = grid.with_columns(
        pl.col("_daily_return")
        .is_not_null()
        .cast(pl.Int64)
        .rolling_sum(_WINDOW, min_samples=_WINDOW)
        .over("symbol")
        .alias("_return_count"),
        pl.col("_daily_return")
        .rolling_max(_WINDOW, min_samples=_WINDOW)
        .over("symbol")
        .alias("_max_return"),
    ).with_columns(
        pl.when(pl.col("_return_count") == _WINDOW)
        .then(pl.col("_max_return"))
        .otherwise(None)
        .alias("max_daily_return_20")
    )
    result = keys.join(
        grid.select("symbol", "trade_date", *FIFTH_BATCH_FACTOR_NAMES),
        on=["symbol", "trade_date"],
        how="left",
        validate="1:1",
    )
    if result.select(
        pl.any_horizontal(
            *[
                pl.col(name).is_infinite() | pl.col(name).is_nan()
                for name in FIFTH_BATCH_FACTOR_NAMES
            ]
        ).any()
    ).item():
        raise ValueError("fifth-batch factors contain non-finite values")
    return result.sort("symbol", "trade_date")


__all__ = [
    "FIFTH_BATCH_FACTOR_NAMES",
    "FIFTH_BATCH_FACTOR_SPECS",
    "compute_fifth_batch_daily_factors",
]
