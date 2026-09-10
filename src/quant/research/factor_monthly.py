"""Carry completed-month liquidity observations onto the daily factor grid."""
import ast
import datetime as dt

import polars as pl

from quant.factors.liquidity import (
    LIQUIDITY_FACTOR_NAMES, compute_monthly_amihud_illiquidity,
    compute_monthly_free_float_turnover_factors,
)


def monthly_input_names(expressions: tuple[str, ...]) -> tuple[str, ...]:
    fields = {node.id for expression in expressions
              for node in ast.walk(ast.parse(expression, mode="eval")) if isinstance(node, ast.Name)}
    return tuple(name for name in LIQUIDITY_FACTOR_NAMES if name in fields)


def attach_monthly_factors(
    panel: pl.DataFrame, bars: pl.DataFrame, basic: pl.DataFrame,
    calendar: tuple[dt.date, ...], names: tuple[str, ...],
) -> pl.DataFrame:
    """Month-end is usable after that close; an invalid new month replaces the old value."""
    if not set(names) <= set(LIQUIDITY_FACTOR_NAMES):
        raise ValueError("Unknown monthly liquidity input")
    if not calendar or calendar != tuple(sorted(set(calendar))):
        raise ValueError("Monthly factors require an ordered exchange calendar")
    low, high = panel["trade_date"].min(), panel["trade_date"].max()
    if not isinstance(low, dt.date) or not isinstance(high, dt.date):
        raise ValueError("Monthly factors require a dated non-empty panel")
    first_dates: dict[tuple[int, int], dt.date] = {}
    signal_dates = []
    for index, day in enumerate(calendar[:-1]):
        month = (day.year, day.month)
        first_dates.setdefault(month, day)
        following = calendar[index + 1]
        if (following.year, following.month) != month and first_dates[month] >= low and day <= high:
            signal_dates.append(day)
    if not signal_dates:
        return panel.with_columns(*[pl.lit(None, dtype=pl.Float64).alias(name) for name in names])
    signals = tuple(signal_dates)
    symbols = tuple(panel["symbol"].unique().sort().to_list())
    monthly = pl.DataFrame({"symbol": symbols}).join(
        pl.DataFrame({"trade_date": signals}), how="cross")
    if LIQUIDITY_FACTOR_NAMES[0] in names:
        amihud = compute_monthly_amihud_illiquidity(
            bars, sessions=calendar, signal_dates=signals, candidate_symbols=symbols)
        monthly = monthly.join(amihud.select("symbol", "trade_date", LIQUIDITY_FACTOR_NAMES[0]),
            on=["symbol", "trade_date"], how="left", validate="1:1")
    turnover = tuple(name for name in names if name != LIQUIDITY_FACTOR_NAMES[0])
    if turnover:
        basic = basic.filter(pl.col("symbol").is_in(symbols)) if not basic.is_empty() else basic
        if basic.is_empty():
            monthly = monthly.with_columns(*[pl.lit(None, dtype=pl.Float64).alias(name) for name in turnover])
        else:
            values = compute_monthly_free_float_turnover_factors(
                basic, signal_dates=signals, candidate_symbols=symbols)
            monthly = monthly.join(values.select("symbol", "trade_date", *turnover),
                on=["symbol", "trade_date"], how="left", validate="1:1")
    result = panel.sort("symbol", "trade_date").join_asof(
        monthly.sort("symbol", "trade_date"), on="trade_date", by="symbol", strategy="backward",
        check_sortedness=False)
    return result.with_columns(*[
        pl.when(pl.col("close").is_not_null()).then(pl.col(name)).otherwise(None).alias(name)
        for name in names])
