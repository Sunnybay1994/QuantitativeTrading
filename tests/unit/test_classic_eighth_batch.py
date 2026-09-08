from __future__ import annotations

import datetime as dt
import math

import polars as pl
import pytest

from quant.factors import classic_eighth_batch as eighth_batch
from quant.factors.classic_eighth_batch import (
    EIGHTH_BATCH_FACTOR_NAMES,
    EIGHTH_BATCH_FACTOR_SPECS,
    compute_eighth_batch_daily_factors,
)




def _sessions(count: int) -> tuple[dt.date, ...]:
    start = dt.date(2025, 1, 2)
    return tuple(start + dt.timedelta(days=index) for index in range(count))


def _bars(
    *,
    sessions: tuple[dt.date, ...],
    lows: dict[str, list[float | None]],
    adj_factors: dict[str, list[float]] | None = None,
) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for symbol, values in lows.items():
        assert len(values) == len(sessions)
        factors = (
            [1.0] * len(sessions)
            if adj_factors is None
            else adj_factors.get(symbol, [1.0] * len(sessions))
        )
        assert len(factors) == len(sessions)
        for trade_date, low, factor in zip(
            sessions,
            values,
            factors,
            strict=True,
        ):
            if low is None:
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "open": low + 1.0,
                    "high": low + 2.0,
                    "low": low,
                    "close": low + 1.0,
                    "volume": 1_000_000.0,
                    "amount": 1_000_000.0,
                    "adj_factor": factor,
                    "source": "fixture",
                }
            )
    return pl.DataFrame(rows)


def _rank_pattern_lows(
    pattern: list[float],
) -> dict[str, list[float | None]]:
    mapping = {
        0.0: (1.0, 2.0, 3.0),
        0.5: (2.0, 1.0, 3.0),
        0.75: (2.0, 1.0, 2.0),
        1.0: (3.0, 1.0, 2.0),
    }
    values = [mapping[value] for value in pattern]
    return {
        "600001.SH": [value[0] for value in values],
        "600002.SH": [value[1] for value in values],
        "600003.SH": [value[2] for value in values],
    }


def _factor_for(
    result: pl.DataFrame,
    *,
    symbol: str,
    trade_date: dt.date,
) -> float | None:
    return (
        result.filter(
            (pl.col("symbol") == symbol)
            & (pl.col("trade_date") == trade_date)
        )
        .get_column("alpha101_004")
        .item()
    )




def test_public_identity_exact_output_and_all_equal_tie() -> None:
    assert EIGHTH_BATCH_FACTOR_NAMES == ("alpha101_004",)
    assert tuple(spec.name for spec in EIGHTH_BATCH_FACTOR_SPECS) == (
        "alpha101_004",
    )
    assert "adjusted_low" in EIGHTH_BATCH_FACTOR_SPECS[0].source

    sessions = _sessions(9)
    bars = _bars(
        sessions=sessions,
        lows={
            "600001.SH": [2.0] * 9,
            "600002.SH": [2.0] * 9,
            "600003.SH": [2.0] * 9,
        },
    )
    result = compute_eighth_batch_daily_factors(bars, sessions=sessions)

    assert result.columns == ["symbol", "trade_date", "alpha101_004"]
    assert result.schema == {
        "symbol": pl.String,
        "trade_date": pl.Date,
        "alpha101_004": pl.Float64,
    }
    assert result.height == bars.height
    assert result.select("symbol", "trade_date").is_sorted(
        "symbol", "trade_date"
    )
    first = result.filter(pl.col("symbol") == "600001.SH")
    assert first.head(8).get_column("alpha101_004").null_count() == 8
    assert first.tail(1).get_column("alpha101_004").item() == pytest.approx(-0.5)


def test_cross_section_rank_is_ascending_average_normalized_and_null_for_one() -> None:
    day1, day2 = _sessions(2)
    frame = pl.DataFrame(
        {
            "symbol": ["A", "B", "C", "D", "A", "B"],
            "trade_date": [day1, day1, day1, day1, day2, day2],
            "_adjusted_low": [1.0, 2.0, 2.0, None, 2.0, None],
        },
        schema={
            "symbol": pl.String,
            "trade_date": pl.Date,
            "_adjusted_low": pl.Float64,
        },
    )

    ranked = eighth_batch._with_cross_section_ranks(frame).sort(
        "trade_date", "symbol"
    )
    assert ranked.filter(pl.col("trade_date") == day1).get_column(
        "_cross_section_rank"
    ).to_list() == [0.0, 0.75, 0.75, None]
    assert ranked.filter(pl.col("trade_date") == day2).get_column(
        "_cross_section_rank"
    ).to_list() == [None, None]

    two_members = eighth_batch._with_cross_section_ranks(
        pl.DataFrame(
            {
                "symbol": ["A", "B"],
                "trade_date": [day1, day1],
                "_adjusted_low": [2.0, 3.0],
            }
        )
    )
    three_members = eighth_batch._with_cross_section_ranks(
        pl.DataFrame(
            {
                "symbol": ["A", "B", "C"],
                "trade_date": [day1, day1, day1],
                "_adjusted_low": [2.0, 3.0, 1.0],
            }
        )
    )
    assert two_members.filter(pl.col("symbol") == "A").get_column(
        "_cross_section_rank"
    ).item() == pytest.approx(0.0)
    assert three_members.filter(pl.col("symbol") == "A").get_column(
        "_cross_section_rank"
    ).item() == pytest.approx(0.5)

    sessions = _sessions(9)
    single_symbol = compute_eighth_batch_daily_factors(
        _bars(
            sessions=sessions,
            lows={"600001.SH": [1.0] * len(sessions)},
        ),
        sessions=sessions,
    )
    assert single_symbol.get_column("alpha101_004").null_count() == (
        single_symbol.height
    )


def test_time_series_average_ties_and_exact_zero_one_boundaries() -> None:
    sessions = _sessions(9)
    tied_pattern = [0.0, 0.5, 0.75, 1.0, 0.0, 0.5, 0.75, 1.0, 0.75]
    tied = compute_eighth_batch_daily_factors(
        _bars(sessions=sessions, lows=_rank_pattern_lows(tied_pattern)),
        sessions=sessions,
    )
    assert _factor_for(
        tied,
        symbol="600001.SH",
        trade_date=sessions[-1],
    ) == pytest.approx(-0.625)

    current_lowest = compute_eighth_batch_daily_factors(
        _bars(
            sessions=sessions,
            lows=_rank_pattern_lows([1.0] * 8 + [0.0]),
        ),
        sessions=sessions,
    )
    zero = _factor_for(
        current_lowest,
        symbol="600001.SH",
        trade_date=sessions[-1],
    )
    assert zero == 0.0
    assert math.copysign(1.0, zero) == 1.0

    current_highest = compute_eighth_batch_daily_factors(
        _bars(
            sessions=sessions,
            lows=_rank_pattern_lows([0.0] * 8 + [1.0]),
        ),
        sessions=sessions,
    )
    assert _factor_for(
        current_highest,
        symbol="600001.SH",
        trade_date=sessions[-1],
    ) == pytest.approx(-1.0)


def test_requires_nine_strict_sessions_and_never_bridges_a_gap() -> None:
    short_sessions = _sessions(8)
    short = compute_eighth_batch_daily_factors(
        _bars(
            sessions=short_sessions,
            lows=_rank_pattern_lows([0.0] * 8),
        ),
        sessions=short_sessions,
    )
    assert short.get_column("alpha101_004").null_count() == short.height

    sessions = _sessions(10)
    complete = compute_eighth_batch_daily_factors(
        _bars(
            sessions=sessions,
            lows=_rank_pattern_lows([0.0] * 10),
        ),
        sessions=sessions,
    )
    first = complete.filter(pl.col("symbol") == "600001.SH")
    assert first.head(8).get_column("alpha101_004").null_count() == 8
    assert first.tail(2).get_column("alpha101_004").null_count() == 0

    gap_lows = _rank_pattern_lows([0.0] * 10)
    gap_lows["600001.SH"][4] = None
    gap = compute_eighth_batch_daily_factors(
        _bars(sessions=sessions, lows=gap_lows),
        sessions=sessions,
    )
    assert _factor_for(
        gap,
        symbol="600001.SH",
        trade_date=sessions[-1],
    ) is None
    assert _factor_for(
        gap,
        symbol="600002.SH",
        trade_date=sessions[-1],
    ) is not None

    head_lows = _rank_pattern_lows([0.0] * 10)
    head_lows["600001.SH"][0] = None
    head_gap = compute_eighth_batch_daily_factors(
        _bars(sessions=sessions, lows=head_lows),
        sessions=sessions,
    )
    assert _factor_for(
        head_gap,
        symbol="600001.SH",
        trade_date=sessions[8],
    ) is None
    assert _factor_for(
        head_gap,
        symbol="600001.SH",
        trade_date=sessions[9],
    ) is not None

    tail_lows = _rank_pattern_lows([0.0] * 10)
    tail_lows["600001.SH"][-1] = None
    tail_bars = _bars(sessions=sessions, lows=tail_lows)
    tail_gap = compute_eighth_batch_daily_factors(tail_bars, sessions=sessions)
    assert tail_gap.height == tail_bars.height
    assert not tail_gap.filter(
        (pl.col("symbol") == "600001.SH")
        & (pl.col("trade_date") == sessions[-1])
    ).height


def test_uses_adjusted_low_instead_of_raw_low() -> None:
    sessions = _sessions(9)
    lows = {
        "600001.SH": [1.0] * 9,
        "600002.SH": [2.0] * 9,
        "600003.SH": [3.0] * 9,
    }
    adjusted = compute_eighth_batch_daily_factors(
        _bars(
            sessions=sessions,
            lows=lows,
            adj_factors={
                "600001.SH": [1.0] * 8 + [4.0],
                "600002.SH": [1.0] * 9,
                "600003.SH": [1.0] * 9,
            },
        ),
        sessions=sessions,
    )
    raw_equivalent = compute_eighth_batch_daily_factors(
        _bars(sessions=sessions, lows=lows),
        sessions=sessions,
    )

    assert _factor_for(
        adjusted,
        symbol="600001.SH",
        trade_date=sessions[-1],
    ) == pytest.approx(-1.0)
    assert _factor_for(
        raw_equivalent,
        symbol="600001.SH",
        trade_date=sessions[-1],
    ) == pytest.approx(-0.5)


@pytest.mark.parametrize(
    ("column", "value"),
    (
        ("low", True),
        ("adj_factor", True),
        ("low", float("nan")),
        ("adj_factor", float("inf")),
        ("adj_factor", float("-inf")),
        ("low", 0.0),
        ("adj_factor", 0.0),
        ("low", -1.0),
        ("adj_factor", -1.0),
    ),
    ids=(
        "boolean-low",
        "boolean-adjustment",
        "nan-low",
        "positive-infinity",
        "negative-infinity",
        "zero-low",
        "zero-adjustment",
        "negative-low",
        "negative-adjustment",
    ),
)
def test_invalid_low_and_adjustment_sources_fail_closed(
    column: str,
    value: object,
) -> None:
    sessions = _sessions(1)
    bars = _bars(
        sessions=sessions,
        lows={"600001.SH": [1.0], "600002.SH": [2.0]},
    ).with_columns(pl.lit(value).alias(column))

    with pytest.raises(ValueError):
        compute_eighth_batch_daily_factors(bars, sessions=sessions)


def test_adjusted_low_overflow_fails_closed() -> None:
    sessions = _sessions(1)
    bars = _bars(
        sessions=sessions,
        lows={"600001.SH": [1.0e308], "600002.SH": [2.0]},
        adj_factors={
            "600001.SH": [1.0e308],
            "600002.SH": [1.0],
        },
    )
    with pytest.raises(
        ValueError,
        match="adjusted-low arithmetic is non-finite",
    ):
        compute_eighth_batch_daily_factors(bars, sessions=sessions)


def test_duplicate_calendar_escape_and_invalid_sessions_fail_closed() -> None:
    sessions = _sessions(9)
    bars = _bars(
        sessions=sessions,
        lows=_rank_pattern_lows([0.0] * 9),
    )
    duplicate = pl.concat(
        [bars, bars.tail(1).with_columns(pl.lit("other").alias("source"))]
    )
    with pytest.raises(ValueError, match="one source per symbol-date"):
        compute_eighth_batch_daily_factors(duplicate, sessions=sessions)
    with pytest.raises(ValueError, match="outside the session calendar"):
        compute_eighth_batch_daily_factors(bars, sessions=sessions[:-1])
    with pytest.raises(ValueError, match="invalid eighth-batch factor request"):
        compute_eighth_batch_daily_factors(bars, sessions=tuple(reversed(sessions)))
    with pytest.raises(ValueError, match="invalid eighth-batch factor request"):
        compute_eighth_batch_daily_factors(
            bars,
            sessions=(sessions[0], sessions[0]),
        )


def test_row_order_is_canonical_only_input_keys_returned_and_values_finite() -> None:
    sessions = _sessions(10)
    bars = _bars(
        sessions=sessions,
        lows=_rank_pattern_lows(
            [0.0, 0.5, 0.75, 1.0, 0.0, 0.5, 0.75, 1.0, 0.75, 0.0]
        ),
    )
    result = compute_eighth_batch_daily_factors(bars, sessions=sessions)
    reversed_result = compute_eighth_batch_daily_factors(
        bars.reverse(),
        sessions=sessions,
    )

    assert result.equals(reversed_result, null_equal=True)
    assert result.height == bars.select("symbol", "trade_date").unique().height
    values = result.get_column("alpha101_004").drop_nulls()
    assert values.is_finite().all()
    assert values.min() >= -1.0
    assert values.max() <= 0.0
