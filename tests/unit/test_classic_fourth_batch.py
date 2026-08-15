from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from quant.factors.classic_fourth_batch import (
    FOURTH_BATCH_FACTOR_NAMES,
    compute_fourth_batch_daily_factors,
)


def _bars(
    *,
    sessions: tuple[dt.date, ...],
    adjusted_closes: list[float] | None = None,
    adjusted_highs: list[float] | None = None,
    adjusted_lows: list[float] | None = None,
    volumes: list[float] | None = None,
    split_after: int | None = None,
) -> pl.DataFrame:
    count = len(sessions)
    closes = adjusted_closes or [100.0 + 2.0 * index for index in range(count)]
    highs = adjusted_highs or [value + 1.0 for value in closes]
    lows = adjusted_lows or [value - 1.0 for value in closes]
    volume_values = volumes or [1_000_000.0 + 10_000.0 * index for index in range(count)]
    rows: list[dict[str, object]] = []
    for index, trade_date in enumerate(sessions):
        factor = 2.0 if split_after is not None and index >= split_after else 1.0
        close = closes[index] / factor
        rows.append(
            {
                "symbol": "600001.SH",
                "trade_date": trade_date,
                "open": close,
                "high": highs[index] / factor,
                "low": lows[index] / factor,
                "close": close,
                "volume": volume_values[index],
                "amount": close * volume_values[index],
                "adj_factor": factor,
                "source": "fixture",
            }
        )
    return pl.DataFrame(rows)


def _sessions(count: int) -> tuple[dt.date, ...]:
    start = dt.date(2025, 1, 1)
    return tuple(start + dt.timedelta(days=index) for index in range(count))


def test_fourth_batch_matches_formulas_and_is_order_and_split_invariant() -> None:
    sessions = _sessions(21)
    plain = _bars(sessions=sessions)
    split = _bars(sessions=sessions, split_after=10)

    result = compute_fourth_batch_daily_factors(plain, sessions=sessions)
    reversed_result = compute_fourth_batch_daily_factors(
        plain.reverse(), sessions=sessions
    )
    split_result = compute_fourth_batch_daily_factors(split, sessions=sessions)

    last = result.tail(1)
    assert last.get_column("alpha158_resi20").item() == pytest.approx(0.0)
    assert last.get_column("alpha158_imxd20").item() == pytest.approx(0.95)
    assert last.get_column("alpha158_vsumd20").item() == pytest.approx(1.0)
    assert result.equals(reversed_result, null_equal=True)
    assert result.select(*FOURTH_BATCH_FACTOR_NAMES).equals(
        split_result.select(*FOURTH_BATCH_FACTOR_NAMES),
        null_equal=True,
    )


def test_imxd_uses_first_extreme_when_values_tie() -> None:
    sessions = _sessions(20)
    highs = [11.0] * 20
    lows = [9.0] * 20
    highs[2] = highs[17] = 20.0
    lows[4] = lows[18] = 5.0
    result = compute_fourth_batch_daily_factors(
        _bars(
            sessions=sessions,
            adjusted_closes=[10.0] * 20,
            adjusted_highs=highs,
            adjusted_lows=lows,
            volumes=[1_000_000.0] * 20,
        ),
        sessions=sessions,
    )

    last = result.tail(1)
    assert last.get_column("alpha158_resi20").item() == pytest.approx(0.0)
    assert last.get_column("alpha158_imxd20").item() == pytest.approx(-0.1)
    assert last.get_column("alpha158_vsumd20").item() is None


def test_missing_session_invalidates_each_rolling_window() -> None:
    sessions = _sessions(22)
    bars = _bars(sessions=sessions).filter(pl.col("trade_date") != sessions[10])
    result = compute_fourth_batch_daily_factors(bars, sessions=sessions)

    assert result.tail(1).select(*FOURTH_BATCH_FACTOR_NAMES).row(0) == (
        None,
        None,
        None,
    )


def test_vsumd_requires_twenty_changes_and_handles_flat_volume() -> None:
    twenty_sessions = _sessions(20)
    short = compute_fourth_batch_daily_factors(
        _bars(sessions=twenty_sessions, volumes=[1_000_000.0] * 20),
        sessions=twenty_sessions,
    )
    assert short.tail(1).get_column("alpha158_vsumd20").item() is None

    twenty_one_sessions = _sessions(21)
    complete = compute_fourth_batch_daily_factors(
        _bars(sessions=twenty_one_sessions, volumes=[1_000_000.0] * 21),
        sessions=twenty_one_sessions,
    )
    assert complete.tail(1).get_column("alpha158_vsumd20").item() == pytest.approx(
        0.0
    )


def test_duplicate_or_out_of_calendar_bars_are_rejected() -> None:
    sessions = _sessions(21)
    bars = _bars(sessions=sessions)
    duplicate = pl.concat(
        [bars, bars.tail(1).with_columns(pl.lit("other").alias("source"))]
    )
    with pytest.raises(ValueError, match="one source per symbol-date"):
        compute_fourth_batch_daily_factors(duplicate, sessions=sessions)

    with pytest.raises(ValueError, match="outside the session calendar"):
        compute_fourth_batch_daily_factors(bars, sessions=sessions[:-1])
