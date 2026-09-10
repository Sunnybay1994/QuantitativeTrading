"""Attach the existing sixty-session market-risk implementation to the library."""
import ast
import datetime as dt

import polars as pl

from quant.factors.classic_market_risk import compute_classic_market_risk_factors

MARKET_FACTOR_NAMES = ("market_beta_60_vs_510300", "downside_beta_60_vs_510300")


def market_input_names(expressions: tuple[str, ...]) -> tuple[str, ...]:
    fields = {node.id for expression in expressions
              for node in ast.walk(ast.parse(expression, mode="eval")) if isinstance(node, ast.Name)}
    return tuple(name for name in MARKET_FACTOR_NAMES if name in fields)


def attach_market_factors(
    panel: pl.DataFrame, bars: pl.DataFrame, benchmark: pl.DataFrame,
    sessions: tuple[dt.date, ...], names: tuple[str, ...],
) -> pl.DataFrame:
    if not set(names) <= set(MARKET_FACTOR_NAMES):
        raise ValueError("Unknown market-risk input")
    if benchmark.is_empty():
        return panel.with_columns(*[pl.lit(None, dtype=pl.Float64).alias(name) for name in names])
    values = compute_classic_market_risk_factors(
        bars, benchmark, sessions=sessions, benchmark_symbol="510300.SH",
    ).select("symbol", "trade_date", *names)
    return panel.join(values, on=["symbol", "trade_date"], how="left", validate="1:1").sort(
        "symbol", "trade_date")
