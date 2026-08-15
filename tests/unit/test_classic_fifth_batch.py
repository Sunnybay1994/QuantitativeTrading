from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from quant.factors.classic_fifth_batch import (
    compute_fifth_batch_daily_factors,
)


def _sessions(count: int) -> tuple[dt.date, ...]:
    start = dt.date(2025, 1, 1)
    return tuple(start + dt.timedelta(days=index) for index in range(count))


def _prices_from_returns(returns: list[float], *, start: float = 100.0) -> list[float]:
    prices = [start]
    for value in returns:
        prices.append(prices[-1] * (1.0 + value))
    return prices


def _bars(
    *,
    sessions: tuple[dt.date, ...],
    adjusted_closes: list[float],
    split_after: int | None = None,
) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for index, (trade_date, adjusted_close) in enumerate(
        zip(sessions, adjusted_closes, strict=True)
    ):
        factor = 2.0 if split_after is not None and index >= split_after else 1.0
        close = adjusted_close / factor
        rows.append(
            {
                "symbol": "600001.SH",
                "trade_date": trade_date,
                "open": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": 1_000_000.0,
                "amount": close * 1_000_000.0,
                "adj_factor": factor,
                "source": "fixture",
            }
        )
    return pl.DataFrame(rows)


def test_max_requires_twenty_returns_and_uses_signed_maximum() -> None:
    returns = [-0.01] * 18 + [0.05, -0.20]
    prices = _prices_from_returns(returns)

    short_sessions = _sessions(20)
    short = compute_fifth_batch_daily_factors(
        _bars(sessions=short_sessions, adjusted_closes=prices[:20]),
        sessions=short_sessions,
    )
    assert short.tail(1).get_column("max_daily_return_20").item() is None

    sessions = _sessions(21)
    complete = compute_fifth_batch_daily_factors(
        _bars(sessions=sessions, adjusted_closes=prices),
        sessions=sessions,
    )
    assert complete.tail(1).get_column("max_daily_return_20").item() == pytest.approx(
        0.05
    )

    negative_prices = _prices_from_returns([-0.02, -0.01] * 10)
    negative = compute_fifth_batch_daily_factors(
        _bars(sessions=sessions, adjusted_closes=negative_prices),
        sessions=sessions,
    )
    assert negative.tail(1).get_column("max_daily_return_20").item() == pytest.approx(
        -0.01
    )


def test_missing_exchange_session_invalidates_window() -> None:
    sessions = _sessions(22)
    bars = _bars(
        sessions=sessions,
        adjusted_closes=_prices_from_returns([0.01] * 21),
    ).filter(pl.col("trade_date") != sessions[10])
    result = compute_fifth_batch_daily_factors(bars, sessions=sessions)

    assert result.tail(1).get_column("max_daily_return_20").item() is None


def test_factor_is_split_order_and_future_invariant() -> None:
    sessions = _sessions(22)
    prices = _prices_from_returns([0.01] * 21)
    plain = _bars(sessions=sessions, adjusted_closes=prices)
    split = _bars(sessions=sessions, adjusted_closes=prices, split_after=10)

    result = compute_fifth_batch_daily_factors(plain, sessions=sessions)
    reversed_result = compute_fifth_batch_daily_factors(
        plain.reverse(), sessions=sessions
    )
    split_result = compute_fifth_batch_daily_factors(split, sessions=sessions)
    assert result.equals(reversed_result, null_equal=True)
    assert result.select("max_daily_return_20").equals(
        split_result.select("max_daily_return_20"),
        null_equal=True,
    )

    changed_future = plain.with_columns(
        pl.when(pl.col("trade_date") == sessions[-1])
        .then(pl.col("open") * 100.0)
        .otherwise(pl.col("open"))
        .alias("open"),
        pl.when(pl.col("trade_date") == sessions[-1])
        .then(pl.col("high") * 100.0)
        .otherwise(pl.col("high"))
        .alias("high"),
        pl.when(pl.col("trade_date") == sessions[-1])
        .then(pl.col("low") * 100.0)
        .otherwise(pl.col("low"))
        .alias("low"),
        pl.when(pl.col("trade_date") == sessions[-1])
        .then(pl.col("close") * 100.0)
        .otherwise(pl.col("close"))
        .alias("close"),
        pl.when(pl.col("trade_date") == sessions[-1])
        .then(pl.col("amount") * 100.0)
        .otherwise(pl.col("amount"))
        .alias("amount"),
    )
    changed = compute_fifth_batch_daily_factors(
        changed_future,
        sessions=sessions,
    )
    as_of = sessions[-2]
    assert result.filter(pl.col("trade_date") == as_of).row(0) == changed.filter(
        pl.col("trade_date") == as_of
    ).row(0)


def test_duplicate_calendar_escape_and_nonfinite_inputs_fail_closed() -> None:
    sessions = _sessions(21)
    bars = _bars(
        sessions=sessions,
        adjusted_closes=_prices_from_returns([0.01] * 20),
    )
    duplicate = pl.concat(
        [bars, bars.tail(1).with_columns(pl.lit("other").alias("source"))]
    )
    with pytest.raises(ValueError, match="one source per symbol-date"):
        compute_fifth_batch_daily_factors(duplicate, sessions=sessions)

    with pytest.raises(ValueError, match="outside the session calendar"):
        compute_fifth_batch_daily_factors(bars, sessions=sessions[:-1])

    nonfinite = bars.with_columns(
        pl.when(pl.col("trade_date") == sessions[-1])
        .then(float("inf"))
        .otherwise(pl.col("open"))
        .alias("open"),
        pl.when(pl.col("trade_date") == sessions[-1])
        .then(float("inf"))
        .otherwise(pl.col("high"))
        .alias("high"),
        pl.when(pl.col("trade_date") == sessions[-1])
        .then(float("inf"))
        .otherwise(pl.col("low"))
        .alias("low"),
        pl.when(pl.col("trade_date") == sessions[-1])
        .then(float("inf"))
        .otherwise(pl.col("close"))
        .alias("close"),
    )
    with pytest.raises(ValueError, match="non-finite adjusted closes"):
        compute_fifth_batch_daily_factors(nonfinite, sessions=sessions)
