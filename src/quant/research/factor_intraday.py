"""Attach minute-derived daily observations before expression rolling windows."""

import ast
import datetime as dt
from collections.abc import Iterable

import polars as pl

from quant.factors.intraday_low_frequency import DAILY_NAMES, compute_intraday_low_frequency_factors


def minute_input_names(expressions: tuple[str, ...]) -> tuple[str, ...]:
    known = {f"minute_{name}" for name in DAILY_NAMES}
    return tuple(sorted({node.id for expression in expressions
        for node in ast.walk(ast.parse(expression, mode="eval"))
        if isinstance(node, ast.Name) and node.id in known}))


def attach_minute_factors(
    panel: pl.DataFrame, minute_inputs: Iterable[pl.DataFrame],
    sessions: tuple[dt.date, ...], names: tuple[str, ...],
) -> pl.DataFrame:
    keys = ["symbol", "trade_date"]
    frames = []
    for minute in minute_inputs:
        daily = compute_intraday_low_frequency_factors(minute, sessions=sessions, window=1, expanded=True)
        frames.append(daily.select(*keys, *[pl.col(name.replace("minute_", "daily_", 1)).alias(name)
                                           for name in names]))
    observations = pl.concat(frames) if frames else pl.DataFrame(
        schema={"symbol": pl.String, "trade_date": pl.Date, **dict.fromkeys(names, pl.Float64)})
    return panel.join(observations, on=keys, how="left", validate="1:1").with_columns(
        pl.when(pl.col("close").is_finite().fill_null(False)).then(pl.col(name)).otherwise(None).alias(name)
        for name in names
    ).sort(*keys)
