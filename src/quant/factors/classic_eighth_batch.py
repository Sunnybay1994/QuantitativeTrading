"""Eighth-batch Alpha101 low-rank reversal factor for M2 research."""

from __future__ import annotations

import datetime as dt

import polars as pl

from quant.domain import Bar1dSchema
from quant.factors.classic import ClassicFactorSpec


EIGHTH_BATCH_FACTOR_SPECS: tuple[ClassicFactorSpec, ...] = (
    ClassicFactorSpec(
        "alpha101_004",
        "Alpha101 #4 local adaptation: -Ts_Rank(rank(adjusted_low), 9)",
        "nine-session reversal in adjusted-low cross-sectional position",
    ),
)

EIGHTH_BATCH_FACTOR_NAMES = tuple(spec.name for spec in EIGHTH_BATCH_FACTOR_SPECS)

_TIME_SERIES_WINDOW = 9
_CROSS_SECTION_MINIMUM = 2
_NUMERIC_SOURCE_COLUMNS = ("low", "adj_factor")


def compute_eighth_batch_daily_factors(
    bars: pl.DataFrame,
    *,
    sessions: tuple[dt.date, ...],
) -> pl.DataFrame:
    """Compute the frozen local Alpha101 #004 adaptation.

    Daily adjusted-low values first receive an ascending, average-tie,
    zero-to-one cross-sectional rank.  The current rank is then ranked within
    exactly nine exchange sessions using the same tie convention and negated.
    A complete symbol-by-session grid prevents missing bars from being bridged.
    """
    if (
        not isinstance(bars, pl.DataFrame)
        or bars.is_empty()
        or type(sessions) is not tuple
        or not sessions
        or any(type(value) is not dt.date for value in sessions)
        or sessions != tuple(sorted(set(sessions)))
    ):
        raise ValueError("invalid eighth-batch factor request")

    if any(
        bars.schema.get(column) == pl.Boolean
        for column in _NUMERIC_SOURCE_COLUMNS
        if column in bars.columns
    ):
        raise ValueError("eighth-batch bars contain boolean numeric sources")

    try:
        clean = Bar1dSchema.validate(bars).sort(
            "symbol", "trade_date", "source"
        )
    except Exception as exc:
        raise ValueError("eighth-batch bars fail Bar1dSchema validation") from exc

    if clean.select(
        pl.struct("symbol", "trade_date").is_duplicated().any()
    ).item():
        raise ValueError("eighth-batch bars must have one source per symbol-date")
    session_set = set(sessions)
    if any(value not in session_set for value in clean.get_column("trade_date")):
        raise ValueError("eighth-batch bars contain dates outside the session calendar")
    if _has_non_finite(clean, _NUMERIC_SOURCE_COLUMNS):
        raise ValueError("eighth-batch bars contain non-finite numeric sources")

    prepared = clean.with_columns(
        (pl.col("low") * pl.col("adj_factor"))
        .cast(pl.Float64)
        .alias("_adjusted_low")
    )
    if _has_non_finite(prepared, ("_adjusted_low",)):
        raise ValueError("eighth-batch adjusted-low arithmetic is non-finite")
    if prepared.select(
        (
            (pl.col("low") <= 0)
            | (pl.col("adj_factor") <= 0)
            | (pl.col("_adjusted_low") <= 0)
        ).any()
    ).item():
        raise ValueError("eighth-batch adjusted-low operands must be positive")

    session_frame = pl.DataFrame(
        {"trade_date": sessions},
        schema={"trade_date": pl.Date},
    )
    symbols = clean.select("symbol").unique().sort("symbol")
    keys = clean.select("symbol", "trade_date").sort("symbol", "trade_date")
    grid = (
        symbols.join(session_frame, how="cross")
        .join(
            prepared.select("symbol", "trade_date", "_adjusted_low"),
            on=["symbol", "trade_date"],
            how="left",
            validate="1:1",
        )
        .sort("symbol", "trade_date")
    )
    grid = _with_cross_section_ranks(grid)

    lag_columns = tuple(
        f"_cross_section_rank_lag_{lag}"
        for lag in range(_TIME_SERIES_WINDOW)
    )
    grid = grid.with_columns(
        *[
            pl.col("_cross_section_rank")
            .shift(lag)
            .over("symbol")
            .alias(column)
            for lag, column in enumerate(lag_columns)
        ]
    )
    current = pl.col(lag_columns[0])
    grid = grid.with_columns(
        pl.sum_horizontal(
            *[
                pl.col(column).is_not_null().cast(pl.Int64)
                for column in lag_columns
            ]
        ).alias("_time_series_count"),
        pl.sum_horizontal(
            *[
                (pl.col(column) < current).cast(pl.Int64)
                for column in lag_columns
            ]
        ).alias("_time_series_less_count"),
        pl.sum_horizontal(
            *[
                (pl.col(column) == current).cast(pl.Int64)
                for column in lag_columns
            ]
        ).alias("_time_series_equal_count"),
    ).with_columns(
        pl.when(pl.col("_time_series_count") == _TIME_SERIES_WINDOW)
        .then(
            (
                pl.col("_time_series_less_count").cast(pl.Float64)
                + (
                    pl.col("_time_series_equal_count").cast(pl.Float64)
                    - 1.0
                )
                / 2.0
            )
            / float(_TIME_SERIES_WINDOW - 1)
        )
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .alias("_time_series_rank")
    )
    grid = grid.with_columns(
        pl.when(pl.col("_time_series_rank") == 0.0)
        .then(0.0)
        .otherwise(-pl.col("_time_series_rank"))
        .cast(pl.Float64)
        .alias("alpha101_004")
    )

    result = (
        keys.join(
            grid.select("symbol", "trade_date", *EIGHTH_BATCH_FACTOR_NAMES),
            on=["symbol", "trade_date"],
            how="left",
            validate="1:1",
        )
        .select(
            pl.col("symbol").cast(pl.String),
            pl.col("trade_date").cast(pl.Date),
            pl.col("alpha101_004").cast(pl.Float64),
        )
        .sort("symbol", "trade_date")
    )
    if _has_non_finite(
        result,
        EIGHTH_BATCH_FACTOR_NAMES,
        non_null_only=True,
    ):
        raise ValueError("eighth-batch factors contain non-finite values")
    if result.filter(
        pl.col("alpha101_004").is_not_null()
        & (
            (pl.col("alpha101_004") < -1.0)
            | (pl.col("alpha101_004") > 0.0)
        )
    ).height:
        raise ValueError("eighth-batch factors fall outside the frozen range")
    return result


def _with_cross_section_ranks(frame: pl.DataFrame) -> pl.DataFrame:
    """Attach the frozen ascending average-tie rank to an adjusted-low grid."""
    return frame.with_columns(
        pl.col("_adjusted_low")
        .count()
        .over("trade_date")
        .alias("_cross_section_count"),
        pl.col("_adjusted_low")
        .rank("average")
        .over("trade_date")
        .alias("_cross_section_average_rank"),
    ).with_columns(
        pl.when(pl.col("_cross_section_count") >= _CROSS_SECTION_MINIMUM)
        .then(
            (pl.col("_cross_section_average_rank") - 1.0)
            / (pl.col("_cross_section_count").cast(pl.Float64) - 1.0)
        )
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .cast(pl.Float64)
        .alias("_cross_section_rank")
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
    "EIGHTH_BATCH_FACTOR_NAMES",
    "EIGHTH_BATCH_FACTOR_SPECS",
    "compute_eighth_batch_daily_factors",
]
