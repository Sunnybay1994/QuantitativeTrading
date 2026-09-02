"""Deterministic cross-sectional component ranks for research consumers."""

from __future__ import annotations

import polars as pl

_INPUT_COLUMNS = ["signal_date", "component", "symbol", "value"]
_INPUT_DTYPES = [pl.Date, pl.String, pl.String, pl.Float64]
_KEY_COLUMNS = ["signal_date", "component", "symbol"]
_OUTPUT_COLUMNS = ["signal_date", "component", "symbol", "normalized_rank"]
_OUTPUT_DTYPES = [pl.Date, pl.String, pl.String, pl.Float64]

_TYPE_ERROR = "CROSS_SECTIONAL_RANK_TYPE_ERROR"
_SCHEMA_ERROR = "CROSS_SECTIONAL_RANK_SCHEMA_ERROR"
_KEY_NULL = "CROSS_SECTIONAL_RANK_KEY_NULL"
_DUPLICATE_KEY = "CROSS_SECTIONAL_RANK_DUPLICATE_KEY"
_NON_FINITE_VALUE = "CROSS_SECTIONAL_RANK_NON_FINITE_VALUE"
_INTERNAL_INVARIANT = "CROSS_SECTIONAL_RANK_INTERNAL_INVARIANT"


def _raise_value_error(code: str) -> None:
    raise ValueError(code)


def _validate_input(frame: pl.DataFrame) -> None:
    """Validate the public input in the frozen total-precedence order."""
    if type(frame) is not pl.DataFrame:
        raise TypeError(_TYPE_ERROR)
    if (
        frame.is_empty()
        or frame.columns != _INPUT_COLUMNS
        or frame.dtypes != _INPUT_DTYPES
    ):
        _raise_value_error(_SCHEMA_ERROR)
    if any(frame.get_column(name).null_count() for name in _KEY_COLUMNS):
        _raise_value_error(_KEY_NULL)
    if frame.select(pl.struct(_KEY_COLUMNS).is_duplicated().any()).item():
        _raise_value_error(_DUPLICATE_KEY)
    if frame.select(
        (pl.col("value").is_not_null() & ~pl.col("value").is_finite()).any()
    ).item():
        _raise_value_error(_NON_FINITE_VALUE)


def _compute_rank(frame: pl.DataFrame) -> pl.DataFrame:
    ranked = (
        frame.with_columns(
            pl.col("value").count().over("signal_date", "component").alias("_n"),
            pl.col("value")
            .rank(method="average")
            .over("signal_date", "component")
            .alias("_average_rank"),
        )
        .with_columns(
            pl.when(pl.col("value").is_null() | (pl.col("_n") < 2))
            .then(pl.lit(None, dtype=pl.Float64))
            .otherwise(
                (pl.col("_average_rank") - 1.0) / (pl.col("_n") - 1).cast(pl.Float64)
            )
            .alias("normalized_rank")
        )
        .select(_OUTPUT_COLUMNS)
        .sort(_KEY_COLUMNS)
    )
    return ranked.with_columns(
        pl.when(pl.col("normalized_rank") == 0.0)
        .then(0.0)
        .otherwise(pl.col("normalized_rank"))
        .alias("normalized_rank")
    )


def _validate_output(frame: pl.DataFrame, result: pl.DataFrame) -> None:
    if (
        result.columns != _OUTPUT_COLUMNS
        or result.dtypes != _OUTPUT_DTYPES
        or result.height != frame.height
        or not result.select(_KEY_COLUMNS).equals(
            frame.select(_KEY_COLUMNS).sort(_KEY_COLUMNS)
        )
        or not result.equals(result.sort(_KEY_COLUMNS))
        or result.select(pl.struct(_KEY_COLUMNS).is_duplicated().any()).item()
    ):
        raise RuntimeError(_INTERNAL_INVARIANT)

    invalid_rank = result.select(
        (
            pl.col("normalized_rank").is_not_null()
            & (
                ~pl.col("normalized_rank").is_finite()
                | (pl.col("normalized_rank") < 0.0)
                | (pl.col("normalized_rank") > 1.0)
            )
        ).any()
    ).item()
    expected_null = frame.with_columns(
        pl.col("value").count().over("signal_date", "component").alias("_n")
    ).select(
        *_KEY_COLUMNS,
        (pl.col("value").is_null() | (pl.col("_n") < 2)).alias("_expected_null"),
    ).sort(_KEY_COLUMNS)
    actual_null = result.select(
        *_KEY_COLUMNS,
        pl.col("normalized_rank").is_null().alias("_expected_null"),
    )
    if invalid_rank or not actual_null.equals(expected_null):
        raise RuntimeError(_INTERNAL_INVARIANT)


def rank_cross_sectional_components(frame: pl.DataFrame) -> pl.DataFrame:
    """Return ascending average-tie normalized ranks per date and component."""
    _validate_input(frame)
    try:
        result = _compute_rank(frame)
        _validate_output(frame, result)
    except RuntimeError as exc:
        if exc.args == (_INTERNAL_INVARIANT,):
            raise
        raise RuntimeError(_INTERNAL_INVARIANT) from None
    except Exception:
        raise RuntimeError(_INTERNAL_INVARIANT) from None
    return result


__all__ = ["rank_cross_sectional_components"]
