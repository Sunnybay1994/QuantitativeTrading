"""Diagnose source and transformation gaps for saved daily value factor rows."""

from __future__ import annotations

import polars as pl


_KEYS = ["symbol", "trade_date"]
_SOURCE_COLUMNS = {
    "daily_dividend_yield_ttm": "dividend_yield_ttm",
    "daily_ep_ttm_positive": "pe_ttm",
}
_VALUE_TOLERANCE = 1e-10


def _validate_keys(frame: pl.DataFrame, *, name: str, required: list[str]) -> None:
    missing = set(required) - set(frame.columns)
    if missing:
        raise ValueError(f"{name} missing required columns: {sorted(missing)}")
    keys = frame.select(_KEYS)
    if keys.select(pl.any_horizontal(pl.all().is_null()).any()).item():
        raise ValueError(f"{name} contains null keys")
    if keys.is_duplicated().any():
        raise ValueError(f"{name} contains duplicate symbol/trade_date keys")


def diagnose_daily_value_inputs(
    *,
    pool: pl.DataFrame,
    basic: pl.DataFrame,
    factor_values: pl.DataFrame,
    factor_id: str,
) -> pl.DataFrame:
    """Return one diagnosis per pool key, preserving pool order and numeric values.

    ``basic`` uses clean ``daily_basic`` names. ``factor_values`` accepts either
    ``symbol`` or ``ts_code`` plus ``trade_date`` and ``value``. All three inputs
    must have unique, non-null keys, including any rows outside the pool; extra
    rows do not contribute to the returned coverage. Inputs are not modified.

    Reasons prioritize source row absence, source null, source NaN/infinity, and
    nonpositive PE before checking factor rows, missing/nonfinite factor values,
    and formula mismatches (absolute tolerance 1e-10). Dividend source values
    retain percentage units; factor values use decimal units. Genuine zero
    dividends are observed values, whereas source nulls remain unknown.

    ``unexpected_factor_value`` independently flags a finite factor value when
    its source is unavailable or PE is definitionally excluded, so source-first
    reasons do not conceal stale or incorrectly filled factor values. This
    diagnostic uses the supplied PIT-aligned rows; it performs no filling or IO.
    """
    if factor_id not in _SOURCE_COLUMNS:
        raise ValueError(f"Unsupported daily value factor: {factor_id}")
    source_column = _SOURCE_COLUMNS[factor_id]
    factors = factor_values
    if "symbol" not in factors.columns and "ts_code" in factors.columns:
        factors = factors.rename({"ts_code": "symbol"})
    _validate_keys(pool, name="pool", required=_KEYS)
    _validate_keys(basic, name="basic", required=[*_KEYS, source_column])
    _validate_keys(factors, name="factor_values", required=[*_KEYS, "value"])

    source = basic.select(
        *_KEYS,
        pl.lit(True).alias("source_row_present"),
        pl.col(source_column).cast(pl.Float64).alias("source_value"),
    )
    factor = factors.select(
        *_KEYS,
        pl.lit(True).alias("factor_row_present"),
        pl.col("value").cast(pl.Float64).alias("factor_value"),
    )
    paired = (
        pool.select(_KEYS)
        .join(source, on=_KEYS, how="left", maintain_order="left")
        .join(factor, on=_KEYS, how="left", maintain_order="left")
        .with_columns(
            pl.col("source_row_present", "factor_row_present").fill_null(False)
        )
    )
    source_value = pl.col("source_value")
    factor_value = pl.col("factor_value")
    source_finite = source_value.is_finite().fill_null(False)
    factor_finite = factor_value.is_finite().fill_null(False)
    nonpositive_pe = (
        (source_value <= 0).fill_null(False)
        if factor_id == "daily_ep_ttm_positive"
        else pl.lit(False)
    )
    source_usable = pl.col("source_row_present") & source_finite & ~nonpositive_pe
    expected = (
        1.0 / source_value
        if factor_id == "daily_ep_ttm_positive"
        else source_value / 100.0
    )
    return paired.with_columns(
        pl.when(~pl.col("source_row_present"))
        .then(pl.lit("source_row_missing"))
        .when(source_value.is_null())
        .then(pl.lit("source_field_null"))
        .when(~source_finite)
        .then(pl.lit("source_nonfinite"))
        .when(nonpositive_pe)
        .then(pl.lit("definition_nonpositive_pe"))
        .when(~pl.col("factor_row_present"))
        .then(pl.lit("factor_row_missing"))
        .when(~factor_finite)
        .then(pl.lit("factor_value_missing"))
        .when((factor_value - expected).abs() > _VALUE_TOLERANCE)
        .then(pl.lit("factor_value_mismatch"))
        .otherwise(pl.lit("observed"))
        .alias("reason"),
        (~source_usable & factor_finite).alias("unexpected_factor_value"),
    )


__all__ = ["diagnose_daily_value_inputs"]
