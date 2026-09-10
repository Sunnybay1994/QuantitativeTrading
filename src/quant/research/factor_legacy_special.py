"""Reuse the three existing factors that are not plain daily expressions."""
import ast
import datetime as dt

import polars as pl

from quant.factors.classic_tenth_batch import compute_tenth_batch_daily_factors
from quant.factors.max_daily_basic_control import compute_max_daily_basic_control
from quant.factors.reversal_volatility import compute_reversal_volatility_factors

LEGACY_SPECIAL_NAMES = (
    "alpha101_007_cny_amount_gate", "max_daily_return_20_size_turnover_residual", "ivol_ff3_60",
)


def legacy_special_input_names(expressions: tuple[str, ...]) -> tuple[str, ...]:
    fields = {node.id for expression in expressions
              for node in ast.walk(ast.parse(expression, mode="eval")) if isinstance(node, ast.Name)}
    return tuple(name for name in LEGACY_SPECIAL_NAMES if name in fields)


def attach_legacy_special_factors(
    panel: pl.DataFrame, bars: pl.DataFrame, basic: pl.DataFrame,
    sessions: tuple[dt.date, ...], names: tuple[str, ...],
) -> pl.DataFrame:
    if not set(names) <= set(LEGACY_SPECIAL_NAMES):
        raise ValueError("Unknown legacy factor input")
    result = panel
    if LEGACY_SPECIAL_NAMES[0] in names:
        values = compute_tenth_batch_daily_factors(bars, sessions=sessions)
        result = result.join(values, on=["symbol", "trade_date"], how="left", validate="1:1")
    for name in names:
        if name == LEGACY_SPECIAL_NAMES[0]:
            continue
        if basic.is_empty():
            result = result.with_columns(pl.lit(None, dtype=pl.Float64).alias(name))
            continue
        if name == LEGACY_SPECIAL_NAMES[1]:
            values, _ = compute_max_daily_basic_control(bars, basic, sessions=sessions,
                minimum_regression_rows=100, maximum_condition_number=1_000_000.0,
                orthogonality_tolerance=1e-10)
        else:
            values, _ = compute_reversal_volatility_factors(bars, basic, sessions=sessions,
                settings={"reversal_window_sessions": 20, "volatility_window_sessions": 60,
                    "ivol_window_sessions": 60, "annualization_sessions": 252,
                    "proxy_minimum_bucket_symbols": 10})
        result = result.join(values.select("symbol", "trade_date", name),
            on=["symbol", "trade_date"], how="left", validate="1:1")
    return result.with_columns(*[
        pl.when(pl.col("close").is_not_null()).then(pl.col(name)).otherwise(None).alias(name)
        for name in names]).sort("symbol", "trade_date")
