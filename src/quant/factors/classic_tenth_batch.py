"""Tenth-batch local Alpha101-inspired amount-gated reversal factor."""

from __future__ import annotations

import datetime as dt

import polars as pl

from quant.domain import Bar1dSchema
from quant.factors.classic import ClassicFactorSpec


TENTH_BATCH_FACTOR_SPECS: tuple[ClassicFactorSpec, ...] = (
    ClassicFactorSpec(
        "alpha101_007_cny_amount_gate",
        (
            "Source alias alpha101_007: ((adv20 < volume) ? "
            "((-1 * ts_rank(abs(delta(close, 7)), 60)) * "
            "sign(delta(close, 7))) : (-1 * 1))"
        ),
        (
            "LOCAL_CNY_AMOUNT_GATE_NOT_FAITHFUL_REPLICATION: current CNY "
            "amount strictly above its inclusive twenty-session mean gates "
            "seven-session adjusted-close reversal"
        ),
    ),
)

TENTH_BATCH_FACTOR_NAMES = ("alpha101_007_cny_amount_gate",)

_DELTA_LAG = 7
_AMOUNT_WINDOW = 20
_RANK_WINDOW = 60
_RANK_DENOMINATOR = _RANK_WINDOW - 1
_NUMERIC_SOURCE_COLUMNS = ("close", "amount", "adj_factor")


def compute_tenth_batch_daily_factors(
    bars: pl.DataFrame,
    *,
    sessions: tuple[dt.date, ...],
) -> pl.DataFrame:
    """Compute the frozen local Alpha101 #007 amount-gated adaptation.

    Calculations use a symbol-by-session grid. A missing bar therefore
    invalidates every affected strict-session window and is never bridged.
    Only keys present in ``bars`` are returned.
    """
    if (
        type(bars) is not pl.DataFrame
        or bars.is_empty()
        or type(sessions) is not tuple
        or not sessions
        or any(type(value) is not dt.date for value in sessions)
        or sessions != tuple(sorted(set(sessions)))
    ):
        raise ValueError("invalid tenth-batch factor request")

    if any(
        bars.schema.get(column) == pl.Boolean
        for column in _NUMERIC_SOURCE_COLUMNS
        if column in bars.columns
    ):
        raise ValueError("tenth-batch bars contain boolean numeric sources")
    try:
        if _has_non_finite(bars, _NUMERIC_SOURCE_COLUMNS):
            raise ValueError("tenth-batch bars contain non-finite numeric sources")
        clean = Bar1dSchema.validate(bars).sort(
            "symbol", "trade_date", "source"
        )
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("tenth-batch bars fail Bar1dSchema validation") from exc

    if clean.select(pl.struct("symbol", "trade_date").is_duplicated().any()).item():
        raise ValueError("tenth-batch bars must have one source per symbol-date")
    session_set = set(sessions)
    if any(value not in session_set for value in clean.get_column("trade_date")):
        raise ValueError("tenth-batch bars contain dates outside the session calendar")

    prepared = clean.with_columns(
        (pl.col("close") * pl.col("adj_factor")).alias("_adjusted_close"),
        pl.when(
            pl.col("amount").is_not_null()
            & pl.col("amount").is_finite()
            & (pl.col("amount") > 0)
        )
        .then(pl.col("amount"))
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .alias("_valid_amount"),
    )
    if _has_non_finite(prepared, ("_adjusted_close",)):
        raise ValueError("tenth-batch adjusted-close arithmetic is non-finite")

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
                "_adjusted_close",
                "_valid_amount",
            ),
            on=["symbol", "trade_date"],
            how="left",
            validate="1:1",
        )
        .sort("symbol", "trade_date")
        .with_columns(
            (
                pl.col("_adjusted_close")
                - pl.col("_adjusted_close").shift(_DELTA_LAG).over("symbol")
            ).alias("_delta7"),
            pl.col("_valid_amount")
            .is_not_null()
            .cast(pl.Int64)
            .rolling_sum(
                _AMOUNT_WINDOW,
                min_samples=_AMOUNT_WINDOW,
            )
            .over("symbol")
            .alias("_amount_count20"),
            _inclusive_amount_mean20("_valid_amount").alias("_amount_mean20"),
        )
        .with_columns(pl.col("_delta7").abs().alias("_abs_delta7"))
    )
    if _has_non_finite(
        grid,
        ("_delta7", "_abs_delta7", "_amount_mean20"),
        non_null_only=True,
    ):
        raise ValueError("tenth-batch rolling arithmetic is non-finite")

    less_count = pl.sum_horizontal(
        *[
            (
                pl.col("_abs_delta7").shift(offset).over("symbol")
                < pl.col("_abs_delta7")
            ).cast(pl.Float64)
            for offset in range(_RANK_WINDOW)
        ]
    )
    equal_count = pl.sum_horizontal(
        *[
            (
                pl.col("_abs_delta7").shift(offset).over("symbol")
                == pl.col("_abs_delta7")
            ).cast(pl.Float64)
            for offset in range(_RANK_WINDOW)
        ]
    )
    grid = grid.with_columns(
        pl.col("_abs_delta7")
        .is_not_null()
        .cast(pl.Int64)
        .rolling_sum(
            _RANK_WINDOW,
            min_samples=_RANK_WINDOW,
        )
        .over("symbol")
        .alias("_rank_count60"),
        (
            (less_count + (equal_count - 1.0) / 2.0)
            / float(_RANK_DENOMINATOR)
        ).alias("_ts_rank60"),
    )
    if _has_non_finite(grid, ("_ts_rank60",), non_null_only=True):
        raise ValueError("tenth-batch rank arithmetic is non-finite")

    complete = (
        (pl.col("_amount_count20") == _AMOUNT_WINDOW)
        & (pl.col("_rank_count60") == _RANK_WINDOW)
        & pl.col("_amount_mean20").is_not_null()
        & pl.col("_amount_mean20").is_finite()
        & pl.col("_ts_rank60").is_not_null()
        & pl.col("_ts_rank60").is_finite()
        & (pl.col("_ts_rank60") >= 0.0)
        & (pl.col("_ts_rank60") <= 1.0)
    )
    grid = grid.with_columns(
        pl.when(complete)
        .then(
            pl.when(pl.col("_valid_amount") > pl.col("_amount_mean20"))
            .then(
                pl.when(pl.col("_delta7") < 0.0)
                .then(pl.col("_ts_rank60"))
                .when(pl.col("_delta7") > 0.0)
                .then(-pl.col("_ts_rank60"))
                .otherwise(pl.lit(0.0, dtype=pl.Float64))
            )
            .otherwise(pl.lit(-1.0, dtype=pl.Float64))
        )
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .cast(pl.Float64)
        .alias("alpha101_007_cny_amount_gate")
    )

    result = (
        keys.join(
            grid.select("symbol", "trade_date", *TENTH_BATCH_FACTOR_NAMES),
            on=["symbol", "trade_date"],
            how="left",
            validate="1:1",
        )
        .select(
            pl.col("symbol").cast(pl.String),
            pl.col("trade_date").cast(pl.Date),
            pl.col("alpha101_007_cny_amount_gate").cast(pl.Float64),
        )
        .sort("symbol", "trade_date")
    )
    if _has_non_finite(result, TENTH_BATCH_FACTOR_NAMES, non_null_only=True):
        raise ValueError("tenth-batch factor contains non-finite values")
    return result


def _inclusive_amount_mean20(column: str) -> pl.Expr:
    """Return the exact offsets 0..19 inclusive rolling mean expression."""
    return (
        pl.col(column)
        .rolling_mean(
            window_size=_AMOUNT_WINDOW,
            min_samples=_AMOUNT_WINDOW,
        )
        .over("symbol")
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
    "TENTH_BATCH_FACTOR_NAMES",
    "TENTH_BATCH_FACTOR_SPECS",
    "compute_tenth_batch_daily_factors",
]
