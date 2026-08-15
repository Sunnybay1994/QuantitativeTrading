from __future__ import annotations

import datetime as dt
import math
from typing import cast

import polars as pl
import pytest
from pandera.errors import SchemaError

from quant.factors.max_daily_basic_control import (
    MAX_DAILY_BASIC_CONTROL_NAMES,
    compute_max_daily_basic_control,
)


def _sessions(count: int = 22) -> tuple[dt.date, ...]:
    start = dt.date(2025, 1, 1)
    return tuple(start + dt.timedelta(days=index) for index in range(count))


def _symbol(index: int) -> str:
    return f"{600000 + index:06d}.SH"


def _fixture(
    *, symbols: int = 101, sessions: tuple[dt.date, ...] | None = None
) -> tuple[pl.DataFrame, pl.DataFrame, tuple[dt.date, ...]]:
    dates = _sessions() if sessions is None else sessions
    bar_rows: list[dict[str, object]] = []
    daily_rows: list[dict[str, object]] = []
    for symbol_index in range(symbols):
        symbol = _symbol(symbol_index)
        max_order = (symbol_index * 37) % symbols
        turnover_order = (symbol_index * 17) % symbols
        returns = [-0.01] * (len(dates) - 1)
        returns[-2] = 0.02 + max_order / 10_000.0
        returns[-1] = -0.005
        price = 100.0 + symbol_index / 100.0
        prices = [price]
        for value in returns:
            prices.append(prices[-1] * (1.0 + value))
        for trade_date, close in zip(dates, prices, strict=True):
            bar_rows.append(
                {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "open": close,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "volume": 1_000_000.0,
                    "amount": close * 1_000_000.0,
                    "adj_factor": 1.0,
                    "source": "fixture",
                }
            )
            total_market_value = 100_000_000.0 * (
                1.0 + symbol_index / symbols
            )
            daily_rows.append(
                {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "close": close,
                    "turnover_rate": 1.0,
                    "turnover_rate_free": 0.5 + turnover_order / 100.0,
                    "volume_ratio": None,
                    "pe": 12.0,
                    "pe_ttm": 10.0,
                    "pb": 2.0,
                    "ps": 5.0,
                    "ps_ttm": 4.0,
                    "dividend_yield": 1.0,
                    "dividend_yield_ttm": 2.0,
                    "total_shares": 10_000_000.0,
                    "float_shares": 8_000_000.0,
                    "free_float_shares": 7_000_000.0,
                    "total_market_value": total_market_value,
                    "circulating_market_value": total_market_value * 0.8,
                    "source": "tushare",
                }
            )
    return pl.DataFrame(bar_rows), pl.DataFrame(daily_rows), dates


def _compute(
    bars: pl.DataFrame,
    daily_basic: pl.DataFrame,
    sessions: tuple[dt.date, ...],
    *,
    minimum_rows: int = 100,
    condition: float = 1_000_000.0,
    tolerance: float = 1e-10,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    return compute_max_daily_basic_control(
        bars,
        daily_basic,
        sessions=sessions,
        minimum_regression_rows=minimum_rows,
        maximum_condition_number=condition,
        orthogonality_tolerance=tolerance,
    )


def test_rank_ols_is_order_invariant_and_satisfies_frozen_normal_equations() -> None:
    bars, daily_basic, sessions = _fixture()
    first, diagnostics = _compute(bars, daily_basic, sessions)
    reversed_result, reversed_diagnostics = _compute(
        bars.reverse(), daily_basic.reverse(), sessions
    )

    assert first.equals(reversed_result, null_equal=True)
    assert diagnostics.equals(reversed_diagnostics, null_equal=True)
    last = diagnostics.filter(pl.col("trade_date") == sessions[-1])
    assert last.select("complete_rows", "regression_valid").row(0) == (101, True)
    assert cast_float(last.get_column("orthogonality_error").item()) <= 1e-10
    assert (
        first.filter(pl.col("trade_date") == sessions[-1])
        .get_column(MAX_DAILY_BASIC_CONTROL_NAMES[0])
        .drop_nulls()
        .len()
        == 101
    )


def test_controls_are_same_close_only_and_missing_rows_fail_closed() -> None:
    bars, daily_basic, sessions = _fixture()
    baseline, _ = _compute(bars, daily_basic, sessions)
    previous_date = sessions[-2]
    changed_future = daily_basic.with_columns(
        pl.when(pl.col("trade_date") == sessions[-1])
        .then(pl.col("total_market_value") * 10.0)
        .otherwise(pl.col("total_market_value"))
        .alias("total_market_value"),
        pl.when(pl.col("trade_date") == sessions[-1])
        .then(pl.col("turnover_rate_free") * 3.0)
        .otherwise(pl.col("turnover_rate_free"))
        .alias("turnover_rate_free"),
    )
    changed, _ = _compute(bars, changed_future, sessions)
    columns = ["symbol", "trade_date", MAX_DAILY_BASIC_CONTROL_NAMES[0]]
    assert baseline.filter(pl.col("trade_date") == previous_date).select(
        columns
    ).equals(
        changed.filter(pl.col("trade_date") == previous_date).select(columns),
        null_equal=True,
    )

    two_missing = daily_basic.with_columns(
        pl.when(
            (pl.col("trade_date") == sessions[-1])
            & pl.col("symbol").is_in((_symbol(0), _symbol(1)))
        )
        .then(None)
        .otherwise(pl.col("turnover_rate_free"))
        .alias("turnover_rate_free")
    )
    result, diagnostics = _compute(bars, two_missing, sessions)
    last = diagnostics.filter(pl.col("trade_date") == sessions[-1])
    assert last.select("complete_rows", "regression_valid").row(0) == (99, False)
    assert (
        result.filter(pl.col("trade_date") == sessions[-1])
        .get_column(MAX_DAILY_BASIC_CONTROL_NAMES[0])
        .drop_nulls()
        .is_empty()
    )


def test_singular_design_and_numeric_boundaries_are_fail_closed() -> None:
    bars, daily_basic, sessions = _fixture()
    singular = daily_basic.with_columns(
        pl.col("total_market_value").rank("average").over("trade_date").alias(
            "turnover_rate_free"
        )
    )
    result, diagnostics = _compute(bars, singular, sessions)
    assert not cast(bool, diagnostics.tail(1).get_column("regression_valid").item())
    assert (
        result.filter(pl.col("trade_date") == sessions[-1])
        .get_column(MAX_DAILY_BASIC_CONTROL_NAMES[0])
        .drop_nulls()
        .is_empty()
    )

    _, baseline = _compute(bars, daily_basic, sessions)
    last = baseline.filter(pl.col("trade_date") == sessions[-1])
    observed_condition = cast_float(last.get_column("condition_number").item())
    observed_error = cast_float(last.get_column("orthogonality_error").item())
    exact, _ = _compute(
        bars,
        daily_basic,
        sessions,
        condition=observed_condition,
        tolerance=max(observed_error, math.nextafter(0.0, 1.0)),
    )
    assert (
        exact.filter(pl.col("trade_date") == sessions[-1])
        .get_column(MAX_DAILY_BASIC_CONTROL_NAMES[0])
        .drop_nulls()
        .len()
        == 101
    )
    below_condition, _ = _compute(
        bars,
        daily_basic,
        sessions,
        condition=math.nextafter(observed_condition, 0.0),
        tolerance=1e-10,
    )
    assert (
        below_condition.filter(pl.col("trade_date") == sessions[-1])
        .get_column(MAX_DAILY_BASIC_CONTROL_NAMES[0])
        .drop_nulls()
        .is_empty()
    )


def test_duplicate_calendar_escape_and_nonfinite_controls_are_rejected() -> None:
    bars, daily_basic, sessions = _fixture()
    duplicate = pl.concat(
        [
            daily_basic,
            daily_basic.tail(1).with_columns(pl.lit("other").alias("source")),
        ]
    )
    with pytest.raises(ValueError, match="one row per symbol-date"):
        _compute(bars, duplicate, sessions)

    escaped = pl.concat(
        [
            daily_basic,
            daily_basic.tail(1).with_columns(
                pl.lit(sessions[-1] + dt.timedelta(days=1)).alias("trade_date")
            ),
        ]
    )
    with pytest.raises(ValueError, match="out-of-calendar"):
        _compute(bars, escaped, sessions)

    nonfinite = daily_basic.with_columns(
        pl.when(pl.col("symbol") == _symbol(0))
        .then(float("inf"))
        .otherwise(pl.col("turnover_rate_free"))
        .alias("turnover_rate_free")
    )
    with pytest.raises(SchemaError):
        _compute(bars, nonfinite, sessions)


def cast_float(value: object) -> float:
    assert isinstance(value, (int, float))
    return float(value)
