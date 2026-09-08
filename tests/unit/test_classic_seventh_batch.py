from __future__ import annotations

import datetime as dt
import math
from pathlib import Path

import polars as pl
import pytest

from quant.factors.classic_seventh_batch import (
    SEVENTH_BATCH_FACTOR_NAMES,
    SEVENTH_BATCH_FACTOR_SPECS,
    compute_seventh_batch_daily_factors,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _sessions(count: int) -> tuple[dt.date, ...]:
    start = dt.date(2025, 1, 2)
    return tuple(start + dt.timedelta(days=index) for index in range(count))


def _bars_for_symbol(
    *,
    symbol: str,
    sessions: tuple[dt.date, ...],
    closes: list[float],
    adj_factors: list[float] | None = None,
) -> pl.DataFrame:
    factors = adj_factors or [1.0] * len(sessions)
    rows: list[dict[str, object]] = []
    for index, trade_date in enumerate(sessions):
        close = closes[index]
        rows.append(
            {
                "symbol": symbol,
                "trade_date": trade_date,
                "open": close,
                "high": close + 1.0,
                "low": max(close - 1.0, close / 2.0),
                "close": close,
                "volume": 1_000_000.0 + index,
                "amount": close * (1_000_000.0 + index),
                "adj_factor": factors[index],
                "source": "fixture",
            }
        )
    return pl.DataFrame(rows)


def _bars(
    *,
    sessions: tuple[dt.date, ...],
    closes: list[float],
    adj_factors: list[float] | None = None,
) -> pl.DataFrame:
    return _bars_for_symbol(
        symbol="600001.SH",
        sessions=sessions,
        closes=closes,
        adj_factors=adj_factors,
    )


def test_public_identity_exact_schema_and_six_close_requirement() -> None:
    assert SEVENTH_BATCH_FACTOR_NAMES == ("alpha101_009",)
    assert tuple(spec.name for spec in SEVENTH_BATCH_FACTOR_SPECS) == (
        "alpha101_009",
    )

    sessions = _sessions(6)
    result = compute_seventh_batch_daily_factors(
        _bars(sessions=sessions, closes=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0]),
        sessions=sessions,
    )

    assert result.columns == ["symbol", "trade_date", "alpha101_009"]
    assert result.schema == {
        "symbol": pl.String,
        "trade_date": pl.Date,
        "alpha101_009": pl.Float64,
    }
    assert result.get_column("alpha101_009").to_list() == [
        None,
        None,
        None,
        None,
        None,
        1.0,
    ]

    short_sessions = _sessions(5)
    short = compute_seventh_batch_daily_factors(
        _bars(
            sessions=short_sessions,
            closes=[1.0, 2.0, 3.0, 4.0, 5.0],
        ),
        sessions=short_sessions,
    )
    assert short.get_column("alpha101_009").null_count() == 5


@pytest.mark.parametrize(
    ("closes", "expected"),
    (
        ([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], 1.0),
        ([6.0, 5.0, 4.0, 3.0, 2.0, 1.0], -1.0),
        ([2.0, 1.0, 2.0, 3.0, 4.0, 5.0], -1.0),
    ),
    ids=("all-positive", "all-negative", "mixed"),
)
def test_exact_positive_negative_and_mixed_branches(
    closes: list[float], expected: float
) -> None:
    sessions = _sessions(6)
    result = compute_seventh_batch_daily_factors(
        _bars(sessions=sessions, closes=closes),
        sessions=sessions,
    )
    assert result.tail(1).get_column("alpha101_009").item() == expected


def test_zero_delta_is_mixed_and_current_zero_is_positive_zero() -> None:
    sessions = _sessions(6)
    historical_zero = compute_seventh_batch_daily_factors(
        _bars(sessions=sessions, closes=[1.0, 2.0, 2.0, 3.0, 4.0, 5.0]),
        sessions=sessions,
    )
    assert historical_zero.tail(1).get_column("alpha101_009").item() == -1.0

    current_zero = compute_seventh_batch_daily_factors(
        _bars(sessions=sessions, closes=[1.0, 2.0, 3.0, 4.0, 5.0, 5.0]),
        sessions=sessions,
    )
    value = current_zero.tail(1).get_column("alpha101_009").item()
    assert value == 0.0
    assert math.copysign(1.0, value) == 1.0


def test_adjusted_price_difference_is_not_raw_return_or_four_delta_state() -> None:
    sessions = _sessions(6)
    adjusted = compute_seventh_batch_daily_factors(
        _bars(
            sessions=sessions,
            closes=[10.0, 9.0, 8.0, 7.0, 6.0, 5.0],
            adj_factors=[1.0, 1.2, 1.5, 2.0, 3.0, 6.0],
        ),
        sessions=sessions,
    )
    assert adjusted.tail(1).get_column("alpha101_009").item() == pytest.approx(
        12.0
    )
    assert adjusted.tail(1).get_column("alpha101_009").item() != pytest.approx(
        30.0 / 18.0 - 1.0
    )

    five_delta_state = compute_seventh_batch_daily_factors(
        _bars(sessions=sessions, closes=[2.0, 1.0, 2.0, 3.0, 4.0, 5.0]),
        sessions=sessions,
    )
    assert five_delta_state.tail(1).get_column("alpha101_009").item() == -1.0


def test_internal_and_edge_gaps_are_local_nulls_without_bridging() -> None:
    sessions = _sessions(6)
    bars = _bars(sessions=sessions, closes=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0])

    internal = compute_seventh_batch_daily_factors(
        bars.filter(pl.col("trade_date") != sessions[2]),
        sessions=sessions,
    )
    assert internal.tail(1).get_column("alpha101_009").item() is None

    missing_first = compute_seventh_batch_daily_factors(
        bars.filter(pl.col("trade_date") != sessions[0]),
        sessions=sessions,
    )
    assert missing_first.tail(1).get_column("alpha101_009").item() is None

    missing_last = compute_seventh_batch_daily_factors(
        bars.filter(pl.col("trade_date") != sessions[-1]),
        sessions=sessions,
    )
    assert missing_last.get_column("alpha101_009").null_count() == 5


def test_multiple_symbols_are_isolated_and_values_are_not_ranked() -> None:
    sessions = _sessions(6)
    first = _bars_for_symbol(
        symbol="600001.SH",
        sessions=sessions,
        closes=[10.0, 12.0, 14.0, 16.0, 18.0, 20.0],
    )
    second = _bars_for_symbol(
        symbol="600002.SH",
        sessions=sessions,
        closes=[2.0, 1.0, 2.0, 3.0, 4.0, 5.0],
    )
    combined = pl.concat([second, first])
    result = compute_seventh_batch_daily_factors(
        combined,
        sessions=sessions,
    )
    values = result.filter(pl.col("trade_date") == sessions[-1]).rows()
    assert values == [
        ("600001.SH", sessions[-1], 2.0),
        ("600002.SH", sessions[-1], -1.0),
    ]

    first_gap = combined.filter(
        ~(
            (pl.col("symbol") == "600001.SH")
            & (pl.col("trade_date") == sessions[2])
        )
    )
    gap_result = compute_seventh_batch_daily_factors(
        first_gap,
        sessions=sessions,
    )
    final = gap_result.filter(pl.col("trade_date") == sessions[-1])
    assert final.get_column("alpha101_009").to_list() == [None, -1.0]


def test_input_order_is_canonical_and_only_input_keys_are_returned() -> None:
    sessions = _sessions(7)
    bars = _bars(
        sessions=sessions,
        closes=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0],
    ).filter(pl.col("trade_date") != sessions[3])
    result = compute_seventh_batch_daily_factors(bars, sessions=sessions)
    reversed_result = compute_seventh_batch_daily_factors(
        bars.reverse(),
        sessions=sessions,
    )

    assert result.equals(reversed_result, null_equal=True)
    assert result.select("symbol", "trade_date").is_sorted("symbol", "trade_date")
    assert result.height == bars.height
    assert result.select("symbol", "trade_date").rows() == (
        bars.select("symbol", "trade_date")
        .sort("symbol", "trade_date")
        .rows()
    )
    assert result.get_column("alpha101_009").drop_nulls().is_finite().all()


@pytest.mark.parametrize(
    ("column", "value"),
    (
        ("close", True),
        ("adj_factor", True),
        ("close", float("nan")),
        ("close", float("inf")),
        ("adj_factor", float("-inf")),
    ),
    ids=("boolean-close", "boolean-factor", "nan", "positive-inf", "negative-inf"),
)
def test_boolean_nan_and_infinity_sources_fail_closed(
    column: str, value: object
) -> None:
    sessions = _sessions(6)
    bars = _bars(
        sessions=sessions,
        closes=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
    ).with_columns(pl.lit(value).alias(column))
    with pytest.raises(ValueError):
        compute_seventh_batch_daily_factors(bars, sessions=sessions)


@pytest.mark.parametrize(("column", "value"), (("close", 0.0), ("adj_factor", 0.0)))
def test_non_positive_price_operands_fail_closed(column: str, value: float) -> None:
    sessions = _sessions(6)
    bars = _bars(
        sessions=sessions,
        closes=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
    ).with_columns(pl.lit(value).alias(column))
    with pytest.raises(ValueError, match="fail Bar1dSchema validation"):
        compute_seventh_batch_daily_factors(bars, sessions=sessions)


def test_adjusted_close_overflow_fails_closed() -> None:
    sessions = _sessions(6)
    bars = _bars(
        sessions=sessions,
        closes=[2.0] * 6,
        adj_factors=[1.0e308] * 6,
    )
    with pytest.raises(ValueError, match="adjusted-close arithmetic is non-finite"):
        compute_seventh_batch_daily_factors(bars, sessions=sessions)


def test_duplicate_calendar_escape_and_invalid_sessions_fail_closed() -> None:
    sessions = _sessions(6)
    bars = _bars(
        sessions=sessions,
        closes=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
    )
    duplicate = pl.concat(
        [bars, bars.tail(1).with_columns(pl.lit("other").alias("source"))]
    )
    with pytest.raises(ValueError, match="one source per symbol-date"):
        compute_seventh_batch_daily_factors(duplicate, sessions=sessions)
    with pytest.raises(ValueError, match="outside the session calendar"):
        compute_seventh_batch_daily_factors(bars, sessions=sessions[:-1])
    with pytest.raises(ValueError, match="invalid seventh-batch factor request"):
        compute_seventh_batch_daily_factors(bars, sessions=tuple(reversed(sessions)))
    with pytest.raises(ValueError, match="invalid seventh-batch factor request"):
        compute_seventh_batch_daily_factors(bars, sessions=(sessions[0], sessions[0]))
