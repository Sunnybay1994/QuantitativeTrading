"""Seventh-batch Alpha101 state-momentum factor for M2 research."""

from __future__ import annotations

import datetime as dt

import polars as pl

from quant.domain import Bar1dSchema
from quant.factors.classic import ClassicFactorSpec


SEVENTH_BATCH_FACTOR_SPECS: tuple[ClassicFactorSpec, ...] = (
    ClassicFactorSpec(
        "alpha101_009",
        "Alpha101 #9 adapted to adjusted-close price differences over five "
        "strict session deltas",
        "short-horizon state momentum with mixed-state reversal",
    ),
)

SEVENTH_BATCH_FACTOR_NAMES = tuple(spec.name for spec in SEVENTH_BATCH_FACTOR_SPECS)

_DELTA_LAG_SESSIONS = 1
_STATE_WINDOW_DELTAS = 5
_NUMERIC_SOURCE_COLUMNS = ("close", "adj_factor")


def compute_seventh_batch_daily_factors(
    bars: pl.DataFrame,
    *,
    sessions: tuple[dt.date, ...],
) -> pl.DataFrame:
    """Compute Alpha101 #009 on a strict symbol-by-session grid.

    A value requires adjusted closes for six consecutive exchange sessions.
    Missing bars therefore invalidate the affected windows and are never
    bridged by using the previous available observation.
    """
    if (
        type(bars) is not pl.DataFrame
        or bars.is_empty()
        or type(sessions) is not tuple
        or not sessions
        or any(type(value) is not dt.date for value in sessions)
        or sessions != tuple(sorted(set(sessions)))
    ):
        raise ValueError("invalid seventh-batch factor request")

    if any(
        bars.schema.get(column) == pl.Boolean
        for column in _NUMERIC_SOURCE_COLUMNS
        if column in bars.columns
    ):
        raise ValueError("seventh-batch bars contain boolean numeric sources")

    try:
        clean = Bar1dSchema.validate(bars).sort(
            "symbol", "trade_date", "source"
        )
    except Exception as exc:
        raise ValueError("seventh-batch bars fail Bar1dSchema validation") from exc

    if clean.select(pl.struct("symbol", "trade_date").is_duplicated().any()).item():
        raise ValueError("seventh-batch bars must have one source per symbol-date")
    session_set = set(sessions)
    if any(value not in session_set for value in clean.get_column("trade_date")):
        raise ValueError(
            "seventh-batch bars contain dates outside the session calendar"
        )
    if _has_non_finite(clean, _NUMERIC_SOURCE_COLUMNS):
        raise ValueError("seventh-batch bars contain non-finite numeric sources")

    prepared = clean.with_columns(
        (pl.col("close") * pl.col("adj_factor")).alias("_adjusted_close")
    )
    if _has_non_finite(prepared, ("_adjusted_close",)):
        raise ValueError("seventh-batch adjusted-close arithmetic is non-finite")

    session_frame = pl.DataFrame(
        {"trade_date": sessions},
        schema={"trade_date": pl.Date},
    )
    symbols = clean.select("symbol").unique().sort("symbol")
    keys = clean.select("symbol", "trade_date").sort("symbol", "trade_date")
    grid = (
        symbols.join(session_frame, how="cross")
        .join(
            prepared.select("symbol", "trade_date", "_adjusted_close"),
            on=["symbol", "trade_date"],
            how="left",
            validate="1:1",
        )
        .sort("symbol", "trade_date")
        .with_columns(
            (
                pl.col("_adjusted_close")
                - pl.col("_adjusted_close")
                .shift(_DELTA_LAG_SESSIONS)
                .over("symbol")
            ).alias("_delta")
        )
    )
    if _has_non_finite(grid, ("_delta",), non_null_only=True):
        raise ValueError("seventh-batch delta arithmetic is non-finite")

    grid = grid.with_columns(
        pl.col("_delta")
        .is_not_null()
        .cast(pl.Int64)
        .rolling_sum(
            _STATE_WINDOW_DELTAS,
            min_samples=_STATE_WINDOW_DELTAS,
        )
        .over("symbol")
        .alias("_delta_count"),
        pl.col("_delta")
        .rolling_min(
            _STATE_WINDOW_DELTAS,
            min_samples=_STATE_WINDOW_DELTAS,
        )
        .over("symbol")
        .alias("_delta_min"),
        pl.col("_delta")
        .rolling_max(
            _STATE_WINDOW_DELTAS,
            min_samples=_STATE_WINDOW_DELTAS,
        )
        .over("symbol")
        .alias("_delta_max"),
    ).with_columns(
        pl.when(pl.col("_delta_count") == _STATE_WINDOW_DELTAS)
        .then(
            pl.when(pl.col("_delta_min") > 0)
            .then(pl.col("_delta"))
            .when(pl.col("_delta_max") < 0)
            .then(pl.col("_delta"))
            .otherwise(-pl.col("_delta"))
        )
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .cast(pl.Float64)
        .alias("_alpha101_009_raw")
    ).with_columns(
        pl.when(pl.col("_alpha101_009_raw") == 0.0)
        .then(pl.lit(0.0))
        .otherwise(pl.col("_alpha101_009_raw"))
        .cast(pl.Float64)
        .alias("alpha101_009")
    )

    result = (
        keys.join(
            grid.select("symbol", "trade_date", *SEVENTH_BATCH_FACTOR_NAMES),
            on=["symbol", "trade_date"],
            how="left",
            validate="1:1",
        )
        .select(
            pl.col("symbol").cast(pl.String),
            pl.col("trade_date").cast(pl.Date),
            pl.col("alpha101_009").cast(pl.Float64),
        )
        .sort("symbol", "trade_date")
    )
    if _has_non_finite(
        result,
        SEVENTH_BATCH_FACTOR_NAMES,
        non_null_only=True,
    ):
        raise ValueError("seventh-batch factors contain non-finite values")
    return result


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
    "SEVENTH_BATCH_FACTOR_NAMES",
    "SEVENTH_BATCH_FACTOR_SPECS",
    "compute_seventh_batch_daily_factors",
]
