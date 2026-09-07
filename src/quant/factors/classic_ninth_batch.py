"""Ninth-batch Alpha101 VWAP-volume-extremes factor for M2 research."""

from __future__ import annotations

import datetime as dt

import polars as pl

from quant.domain import Bar1dSchema
from quant.factors.classic import ClassicFactorSpec


NINTH_BATCH_FACTOR_SPECS: tuple[ClassicFactorSpec, ...] = (
    ClassicFactorSpec(
        "alpha101_011",
        (
            "Alpha101 #11 local adaptation: "
            "(rank(max3(adjusted VWAP-close gap)) + "
            "rank(min3(adjusted VWAP-close gap))) * rank(delta3(raw volume))"
        ),
        "three-session adjusted VWAP-gap extremes and raw-volume change",
    ),
)

NINTH_BATCH_FACTOR_NAMES = tuple(spec.name for spec in NINTH_BATCH_FACTOR_SPECS)

_GAP_EXTREME_WINDOW = 3
_VOLUME_DELTA_LAG = 3
_REQUIRED_BAR_SESSIONS = 4
_CROSS_SECTION_MINIMUM = 2
_NUMERIC_SOURCE_COLUMNS = ("close", "volume", "amount", "adj_factor")


def compute_ninth_batch_daily_factors(
    bars: pl.DataFrame,
    *,
    sessions: tuple[dt.date, ...],
) -> pl.DataFrame:
    """Compute the frozen local Alpha101 #011 adaptation.

    The complete symbol-by-session grid makes both the three-session gap
    extrema and the three-session raw-volume lag fail closed across missing
    bars.  Each component is cross-sectionally ranked on its own finite set.
    """
    if (
        not isinstance(bars, pl.DataFrame)
        or bars.is_empty()
        or type(sessions) is not tuple
        or not sessions
        or any(type(value) is not dt.date for value in sessions)
        or sessions != tuple(sorted(set(sessions)))
    ):
        raise ValueError("invalid ninth-batch factor request")

    if any(
        bars.schema.get(column) == pl.Boolean
        for column in _NUMERIC_SOURCE_COLUMNS
        if column in bars.columns
    ):
        raise ValueError("ninth-batch bars contain boolean numeric sources")

    try:
        clean = Bar1dSchema.validate(bars).sort(
            "symbol", "trade_date", "source"
        )
    except Exception as exc:
        raise ValueError("ninth-batch bars fail Bar1dSchema validation") from exc

    if clean.select(
        pl.struct("symbol", "trade_date").is_duplicated().any()
    ).item():
        raise ValueError("ninth-batch bars must have one source per symbol-date")
    session_set = set(sessions)
    if any(value not in session_set for value in clean.get_column("trade_date")):
        raise ValueError("ninth-batch bars contain dates outside the session calendar")
    if _has_non_finite(clean, _NUMERIC_SOURCE_COLUMNS):
        raise ValueError("ninth-batch bars contain non-finite numeric sources")

    prepared = clean.with_columns(
        pl.when((pl.col("amount") > 0) & (pl.col("volume") > 0))
        .then(pl.col("amount") / pl.col("volume"))
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .cast(pl.Float64)
        .alias("_raw_vwap"),
        (pl.col("close") * pl.col("adj_factor"))
        .cast(pl.Float64)
        .alias("_adjusted_close"),
    ).with_columns(
        (pl.col("_raw_vwap") * pl.col("adj_factor"))
        .cast(pl.Float64)
        .alias("_adjusted_vwap")
    ).with_columns(
        (pl.col("_adjusted_vwap") - pl.col("_adjusted_close"))
        .cast(pl.Float64)
        .alias("_adjusted_gap")
    )
    if _has_non_finite(
        prepared,
        ("_raw_vwap", "_adjusted_vwap", "_adjusted_gap"),
        non_null_only=True,
    ) or _has_non_finite(prepared, ("_adjusted_close",)):
        raise ValueError("ninth-batch VWAP-gap arithmetic is non-finite")

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
                "_adjusted_gap",
            ).with_columns(pl.lit(1, dtype=pl.Int64).alias("_bar_present")),
            on=["symbol", "trade_date"],
            how="left",
            validate="1:1",
        )
        .sort("symbol", "trade_date")
        .with_columns(
            pl.col("_adjusted_gap")
            .is_not_null()
            .cast(pl.Int64)
            .rolling_sum(
                _GAP_EXTREME_WINDOW,
                min_samples=_GAP_EXTREME_WINDOW,
            )
            .over("symbol")
            .alias("_gap_count_3"),
            pl.col("_adjusted_gap")
            .rolling_max(
                _GAP_EXTREME_WINDOW,
                min_samples=_GAP_EXTREME_WINDOW,
            )
            .over("symbol")
            .alias("_gap_max_3_raw"),
            pl.col("_adjusted_gap")
            .rolling_min(
                _GAP_EXTREME_WINDOW,
                min_samples=_GAP_EXTREME_WINDOW,
            )
            .over("symbol")
            .alias("_gap_min_3_raw"),
            pl.col("_bar_present")
            .fill_null(0)
            .rolling_sum(
                _REQUIRED_BAR_SESSIONS,
                min_samples=_REQUIRED_BAR_SESSIONS,
            )
            .over("symbol")
            .alias("_bar_count_4"),
            (
                pl.col("volume")
                - pl.col("volume").shift(_VOLUME_DELTA_LAG).over("symbol")
            ).alias("_volume_delta_3_raw"),
        )
        .with_columns(
            pl.when(pl.col("_gap_count_3") == _GAP_EXTREME_WINDOW)
            .then(pl.col("_gap_max_3_raw"))
            .otherwise(pl.lit(None, dtype=pl.Float64))
            .cast(pl.Float64)
            .alias("_gap_max_3"),
            pl.when(pl.col("_gap_count_3") == _GAP_EXTREME_WINDOW)
            .then(pl.col("_gap_min_3_raw"))
            .otherwise(pl.lit(None, dtype=pl.Float64))
            .cast(pl.Float64)
            .alias("_gap_min_3"),
            pl.when(pl.col("_bar_count_4") == _REQUIRED_BAR_SESSIONS)
            .then(pl.col("_volume_delta_3_raw"))
            .otherwise(pl.lit(None, dtype=pl.Float64))
            .cast(pl.Float64)
            .alias("_volume_delta_3"),
        )
    )
    if _has_non_finite(
        grid,
        ("_gap_max_3", "_gap_min_3", "_volume_delta_3"),
        non_null_only=True,
    ):
        raise ValueError("ninth-batch rolling arithmetic is non-finite")

    grid = _with_component_rank(
        grid,
        value_column="_gap_max_3",
        rank_column="_rank_gap_max_3",
    )
    grid = _with_component_rank(
        grid,
        value_column="_gap_min_3",
        rank_column="_rank_gap_min_3",
    )
    grid = _with_component_rank(
        grid,
        value_column="_volume_delta_3",
        rank_column="_rank_volume_delta_3",
    )

    combined = (
        (pl.col("_rank_gap_max_3") + pl.col("_rank_gap_min_3"))
        * pl.col("_rank_volume_delta_3")
    )
    grid = grid.with_columns(
        pl.when(
            pl.col("_rank_gap_max_3").is_not_null()
            & pl.col("_rank_gap_min_3").is_not_null()
            & pl.col("_rank_volume_delta_3").is_not_null()
        )
        .then(pl.when(combined == 0.0).then(0.0).otherwise(combined))
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .cast(pl.Float64)
        .alias("alpha101_011")
    )

    result = (
        keys.join(
            grid.select("symbol", "trade_date", *NINTH_BATCH_FACTOR_NAMES),
            on=["symbol", "trade_date"],
            how="left",
            validate="1:1",
        )
        .select(
            pl.col("symbol").cast(pl.String),
            pl.col("trade_date").cast(pl.Date),
            pl.col("alpha101_011").cast(pl.Float64),
        )
        .sort("symbol", "trade_date")
    )
    if _has_non_finite(
        result,
        NINTH_BATCH_FACTOR_NAMES,
        non_null_only=True,
    ):
        raise ValueError("ninth-batch factors contain non-finite values")
    if result.filter(
        pl.col("alpha101_011").is_not_null()
        & (
            (pl.col("alpha101_011") < 0.0)
            | (pl.col("alpha101_011") > 2.0)
        )
    ).height:
        raise ValueError("ninth-batch factors fall outside the frozen range")
    return result


def _with_component_rank(
    frame: pl.DataFrame,
    *,
    value_column: str,
    rank_column: str,
) -> pl.DataFrame:
    """Attach one independent ascending average-tie normalized rank."""
    count_column = f"{rank_column}_count"
    average_column = f"{rank_column}_average"
    return frame.with_columns(
        pl.col(value_column)
        .count()
        .over("trade_date")
        .alias(count_column),
        pl.col(value_column)
        .rank("average")
        .over("trade_date")
        .alias(average_column),
    ).with_columns(
        pl.when(pl.col(count_column) >= _CROSS_SECTION_MINIMUM)
        .then(
            (pl.col(average_column) - 1.0)
            / (pl.col(count_column).cast(pl.Float64) - 1.0)
        )
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .cast(pl.Float64)
        .alias(rank_column)
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
    "NINTH_BATCH_FACTOR_NAMES",
    "NINTH_BATCH_FACTOR_SPECS",
    "compute_ninth_batch_daily_factors",
]
