"""Eleventh-batch Alpha101 #002 price-volume divergence factor."""

from __future__ import annotations

import datetime as dt

import polars as pl

from quant.domain import Bar1dSchema
from quant.factors.classic import ClassicFactorSpec
from quant.factors.cross_sectional_rank import rank_cross_sectional_components


ELEVENTH_BATCH_FACTOR_SPECS: tuple[ClassicFactorSpec, ...] = (
    ClassicFactorSpec(
        "alpha101_002",
        "Alpha101 #002: -correlation(rank(delta(log(volume), 2)), "
        "rank((close-open)/open), 6)",
        "six-session price-volume divergence",
    ),
)
ELEVENTH_BATCH_FACTOR_NAMES = tuple(spec.name for spec in ELEVENTH_BATCH_FACTOR_SPECS)

_NUMERIC_SOURCE_COLUMNS = ("open", "close", "volume", "adj_factor")
_REQUIRED_SESSIONS = 8
_CORRELATION_WINDOW = 6


def compute_eleventh_batch_daily_factors(
    bars: pl.DataFrame,
    *,
    sessions: tuple[dt.date, ...],
) -> pl.DataFrame:
    """Compute the frozen local Alpha101 #002 adaptation.

    The public rank helper is called exactly once with both component columns in
    one long-form frame.  Missing bars remain explicit grid rows so lag and
    rolling windows cannot bridge a session gap.
    """
    if (
        type(bars) is not pl.DataFrame
        or bars.is_empty()
        or type(sessions) is not tuple
        or not sessions
        or any(type(value) is not dt.date for value in sessions)
        or sessions != tuple(sorted(set(sessions)))
    ):
        raise ValueError("invalid eleventh-batch factor request")
    if any(bars.schema.get(column) == pl.Boolean for column in _NUMERIC_SOURCE_COLUMNS):
        raise ValueError("eleventh-batch bars contain boolean numeric sources")
    try:
        clean = Bar1dSchema.validate(bars).sort("symbol", "trade_date", "source")
    except Exception as exc:
        raise ValueError("eleventh-batch bars fail Bar1dSchema validation") from exc
    if clean.select(pl.struct("symbol", "trade_date").is_duplicated().any()).item():
        raise ValueError("eleventh-batch bars must have one source per symbol-date")
    session_set = set(sessions)
    if any(value not in session_set for value in clean.get_column("trade_date")):
        raise ValueError("eleventh-batch bars contain dates outside the session calendar")
    if _has_non_finite(clean, _NUMERIC_SOURCE_COLUMNS):
        raise ValueError("eleventh-batch bars contain non-finite numeric sources")

    session_frame = pl.DataFrame({"trade_date": sessions}, schema={"trade_date": pl.Date})
    symbols = clean.select("symbol").unique().sort("symbol")
    keys = clean.select("symbol", "trade_date").sort("symbol", "trade_date")
    present = clean.select("symbol", "trade_date", "open", "close", "volume").with_columns(
        pl.lit(1, dtype=pl.Int64).alias("_bar_present")
    )
    grid = (
        symbols.join(session_frame, how="cross")
        .join(present, on=["symbol", "trade_date"], how="left", validate="1:1")
        .sort("symbol", "trade_date")
        .with_columns(
            ((pl.col("close") - pl.col("open")) / pl.col("open"))
            .cast(pl.Float64)
            .alias("_intraday_return"),
            pl.col("volume").shift(2).over("symbol").alias("_volume_lag2"),
            pl.col("_bar_present").shift(1).over("symbol").alias("_bar_present_lag1"),
        )
        .with_columns(
            pl.when(
                (pl.col("_bar_present") == 1)
                & (pl.col("_bar_present_lag1") == 1)
                & (pl.col("_volume_lag2") > 0)
                & (pl.col("volume") > 0)
            )
            .then(pl.col("volume").log() - pl.col("_volume_lag2").log())
            .otherwise(pl.lit(None, dtype=pl.Float64))
            .cast(pl.Float64)
            .alias("_volume_change"),
            pl.when(pl.col("_bar_present") == 1)
            .then(pl.col("_intraday_return"))
            .otherwise(pl.lit(None, dtype=pl.Float64))
            .cast(pl.Float64)
            .alias("_intraday_return_valid"),
        )
    )
    if _has_non_finite(
        grid,
        ("_volume_change", "_intraday_return_valid"),
        non_null_only=True,
    ):
        raise ValueError("eleventh-batch feature arithmetic is non-finite")

    long_form = pl.concat(
        [
            grid.select(
                pl.col("trade_date").alias("signal_date"),
                pl.lit("volume_change", dtype=pl.String).alias("component"),
                "symbol",
                pl.col("_volume_change").alias("value"),
            ),
            grid.select(
                pl.col("trade_date").alias("signal_date"),
                pl.lit("intraday_return", dtype=pl.String).alias("component"),
                "symbol",
                pl.col("_intraday_return_valid").alias("value"),
            ),
        ],
        how="vertical",
    ).select(
        pl.col("signal_date").cast(pl.Date),
        pl.col("component").cast(pl.String),
        pl.col("symbol").cast(pl.String),
        pl.col("value").cast(pl.Float64),
    )
    ranked = rank_cross_sectional_components(long_form)
    volume_rank = ranked.filter(pl.col("component") == "volume_change").select(
        pl.col("signal_date").alias("trade_date"),
        "symbol",
        pl.col("normalized_rank").alias("_u"),
    )
    return_rank = ranked.filter(pl.col("component") == "intraday_return").select(
        pl.col("signal_date").alias("trade_date"),
        "symbol",
        pl.col("normalized_rank").alias("_r"),
    )
    grid = grid.join(volume_rank, on=["symbol", "trade_date"], how="left", validate="1:1").join(
        return_rank, on=["symbol", "trade_date"], how="left", validate="1:1"
    )
    pair = pl.col("_u").is_not_null() & pl.col("_r").is_not_null()
    grid = grid.with_columns(
        pair.cast(pl.Int64).rolling_sum(_CORRELATION_WINDOW, min_samples=_CORRELATION_WINDOW)
        .over("symbol")
        .alias("_pair_count"),
        (pl.col("_u") * pl.col("_r")).rolling_sum(
            _CORRELATION_WINDOW, min_samples=_CORRELATION_WINDOW
        ).over("symbol").alias("_ur_sum"),
        pl.col("_u").rolling_sum(
            _CORRELATION_WINDOW, min_samples=_CORRELATION_WINDOW
        ).over("symbol").alias("_u_sum"),
        pl.col("_r").rolling_sum(
            _CORRELATION_WINDOW, min_samples=_CORRELATION_WINDOW
        ).over("symbol").alias("_r_sum"),
        (pl.col("_u") ** 2).rolling_sum(
            _CORRELATION_WINDOW, min_samples=_CORRELATION_WINDOW
        ).over("symbol").alias("_u2_sum"),
        (pl.col("_r") ** 2).rolling_sum(
            _CORRELATION_WINDOW, min_samples=_CORRELATION_WINDOW
        ).over("symbol").alias("_r2_sum"),
    ).with_columns(
        (
            pl.col("_u2_sum") - pl.col("_u_sum") ** 2 / _CORRELATION_WINDOW
        ).alias("_u_ss"),
        (
            pl.col("_r2_sum") - pl.col("_r_sum") ** 2 / _CORRELATION_WINDOW
        ).alias("_r_ss"),
        (
            pl.col("_ur_sum") - pl.col("_u_sum") * pl.col("_r_sum") / _CORRELATION_WINDOW
        ).alias("_cross_ss"),
    ).with_columns(
        pl.when(
            (pl.col("_pair_count") == _CORRELATION_WINDOW)
            & (pl.col("_u_ss") > 0.0)
            & (pl.col("_r_ss") > 0.0)
        )
        .then(-pl.col("_cross_ss") / (pl.col("_u_ss") * pl.col("_r_ss")).sqrt())
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .cast(pl.Float64)
        .alias("alpha101_002")
    )
    result = keys.join(
        grid.select("symbol", "trade_date", "alpha101_002"),
        on=["symbol", "trade_date"],
        how="left",
        validate="1:1",
    ).select(
        pl.col("symbol").cast(pl.String),
        pl.col("trade_date").cast(pl.Date),
        pl.col("alpha101_002").cast(pl.Float64),
    ).sort("symbol", "trade_date")
    if _has_non_finite(result, ("alpha101_002",), non_null_only=True):
        raise ValueError("eleventh-batch factors contain non-finite values")
    return result.with_columns(
        pl.when(pl.col("alpha101_002") == 0.0)
        .then(0.0)
        .otherwise(pl.col("alpha101_002"))
        .alias("alpha101_002")
    )


def _has_non_finite(frame: pl.DataFrame, columns: tuple[str, ...], *, non_null_only: bool = False) -> bool:
    expressions: list[pl.Expr] = []
    for column in columns:
        expression = pl.col(column).is_finite()
        expressions.append(pl.col(column).is_not_null() & ~expression if non_null_only else ~expression)
    return bool(frame.select(pl.any_horizontal(*expressions).fill_null(False).any()).item())


__all__ = [
    "ELEVENTH_BATCH_FACTOR_NAMES",
    "ELEVENTH_BATCH_FACTOR_SPECS",
    "compute_eleventh_batch_daily_factors",
]
