from __future__ import annotations

import datetime as dt
import math

import polars as pl
import pytest

from quant.factors.classic_tenth_batch import (
    TENTH_BATCH_FACTOR_NAMES,
    TENTH_BATCH_FACTOR_SPECS,
    _inclusive_amount_mean20,
    compute_tenth_batch_daily_factors,
)


_FACTOR = "alpha101_007_cny_amount_gate"


def _sessions(count: int) -> tuple[dt.date, ...]:
    start = dt.date(2025, 1, 2)
    return tuple(start + dt.timedelta(days=index) for index in range(count))


def _closes_from_delta7(
    deltas: list[float],
    *,
    initial: float = 1_000.0,
) -> list[float]:
    closes = [initial] * 7
    for delta in deltas:
        closes.append(closes[-7] + delta)
    return closes


def _bars(
    *,
    sessions: tuple[dt.date, ...],
    closes: list[float] | None = None,
    amounts: list[float] | None = None,
    volumes: list[float] | None = None,
    adj_factors: list[float] | None = None,
    symbols: tuple[str, ...] = ("600001.SH",),
) -> pl.DataFrame:
    count = len(sessions)
    close_values = closes or [1_000.0 - index for index in range(count)]
    amount_values = amounts or [100.0 + index for index in range(count)]
    volume_values = volumes or [1_000.0] * count
    factor_values = adj_factors or [1.0] * count
    assert all(
        len(values) == count
        for values in (
            close_values,
            amount_values,
            volume_values,
            factor_values,
        )
    )

    rows: list[dict[str, object]] = []
    for symbol in symbols:
        for index, trade_date in enumerate(sessions):
            close = close_values[index]
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": volume_values[index],
                    "amount": amount_values[index],
                    "adj_factor": factor_values[index],
                    "source": "fixture",
                }
            )
    return pl.DataFrame(rows)


def _final_value(
    deltas: list[float],
    *,
    amounts: list[float] | None = None,
    volumes: list[float] | None = None,
) -> float | None:
    sessions = _sessions(len(deltas) + 7)
    result = compute_tenth_batch_daily_factors(
        _bars(
            sessions=sessions,
            closes=_closes_from_delta7(deltas),
            amounts=amounts,
            volumes=volumes,
        ),
        sessions=sessions,
    )
    return result.tail(1).get_column(_FACTOR).item()


def test_public_identity_source_adaptation_and_exact_output_contract() -> None:
    assert TENTH_BATCH_FACTOR_NAMES == (_FACTOR,)
    assert tuple(spec.name for spec in TENTH_BATCH_FACTOR_SPECS) == (_FACTOR,)
    spec = TENTH_BATCH_FACTOR_SPECS[0]
    assert "alpha101_007" in spec.source
    assert "adv20 < volume" in spec.source
    assert "LOCAL_CNY_AMOUNT_GATE_NOT_FAITHFUL_REPLICATION" in spec.mechanism
    assert spec.name != "alpha101_007"

    sessions = _sessions(67)
    result = compute_tenth_batch_daily_factors(
        _bars(
            sessions=sessions,
            closes=_closes_from_delta7([-1.0] * 60),
        ),
        sessions=sessions,
    )
    assert result.columns == ["symbol", "trade_date", _FACTOR]
    assert result.schema == {
        "symbol": pl.String,
        "trade_date": pl.Date,
        _FACTOR: pl.Float64,
    }
    assert not result.filter(
        pl.col(_FACTOR).is_not_null() & ~pl.col(_FACTOR).is_finite()
    ).height


def test_exact_sixty_seven_sessions_produce_the_first_value() -> None:
    short_sessions = _sessions(66)
    short = compute_tenth_batch_daily_factors(
        _bars(
            sessions=short_sessions,
            closes=_closes_from_delta7([-1.0] * 59),
        ),
        sessions=short_sessions,
    )
    assert short.get_column(_FACTOR).null_count() == 66

    sessions = _sessions(67)
    exact = compute_tenth_batch_daily_factors(
        _bars(
            sessions=sessions,
            closes=_closes_from_delta7([-1.0] * 60),
        ),
        sessions=sessions,
    )
    assert exact.head(66).get_column(_FACTOR).null_count() == 66
    assert exact.tail(1).get_column(_FACTOR).item() == pytest.approx(0.5)

    long_sessions = _sessions(68)
    long = compute_tenth_batch_daily_factors(
        _bars(
            sessions=long_sessions,
            closes=_closes_from_delta7([-1.0] * 61),
        ),
        sessions=long_sessions,
    )
    non_null_dates = long.filter(pl.col(_FACTOR).is_not_null()).get_column(
        "trade_date"
    )
    assert non_null_dates.to_list() == list(long_sessions[66:])


def test_amount_gate_strict_greater_equal_and_less_boundaries() -> None:
    deltas = [-1.0] * 60
    greater = [100.0] * 66 + [101.0]
    equal = [100.0] * 67
    less = [100.0] * 66 + [99.0]

    assert _final_value(deltas, amounts=greater) == pytest.approx(0.5)
    assert _final_value(deltas, amounts=equal) == -1.0
    assert _final_value(deltas, amounts=less) == -1.0


def test_gate_uses_cny_amount_not_volume_or_price_times_volume() -> None:
    deltas = [-1.0] * 60
    amount_triggered = [100.0] * 66 + [200.0]
    volume_falls = [1_000_000.0] * 66 + [1.0]
    assert _final_value(
        deltas,
        amounts=amount_triggered,
        volumes=volume_falls,
    ) == pytest.approx(0.5)

    amount_inactive = [100.0] * 66 + [50.0]
    volume_spikes = [1.0] * 66 + [1_000_000.0]
    assert _final_value(
        deltas,
        amounts=amount_inactive,
        volumes=volume_spikes,
    ) == -1.0


def test_amount_mean_uses_exact_inclusive_offsets_zero_through_nineteen() -> None:
    values = [1.0] * 19 + [21.0, 41.0]
    observed = (
        pl.DataFrame(
            {"symbol": ["600001.SH"] * 21, "amount": values},
            schema={"symbol": pl.String, "amount": pl.Float64},
        )
        .with_columns(_inclusive_amount_mean20("amount").alias("mean20"))
        .get_column("mean20")
    )

    assert observed.head(19).null_count() == 19
    assert observed[19] == pytest.approx(sum(values[0:20]) / 20.0)
    assert observed[20] == pytest.approx(sum(values[1:21]) / 20.0)
    assert observed[19] != pytest.approx(sum(values[1:20]) / 19.0)
    assert observed[20] != pytest.approx(sum(values[0:21]) / 21.0)


def test_ts_rank_is_ascending_average_tie_and_normalized_zero_one() -> None:
    assert _final_value([-1.0] * 60) == pytest.approx(0.5)
    assert _final_value([-2.0] * 59 + [-1.0]) == 0.0
    assert _final_value([-1.0] * 59 + [-2.0]) == 1.0

    tied_maximum = _final_value([-1.0] * 58 + [-2.0, -2.0])
    assert tied_maximum == pytest.approx(58.5 / 59.0)


def test_delta_sign_zero_and_inactive_output_branches() -> None:
    active_amounts = [100.0] * 66 + [200.0]
    assert _final_value([-1.0] * 60, amounts=active_amounts) == pytest.approx(0.5)
    assert _final_value([1.0] * 60, amounts=active_amounts) == pytest.approx(-0.5)

    zero = _final_value([-1.0] * 59 + [0.0], amounts=active_amounts)
    assert zero == 0.0
    assert math.copysign(1.0, zero) == 1.0

    inactive_amounts = [100.0] * 67
    assert _final_value([-1.0] * 60, amounts=inactive_amounts) == -1.0


def test_inactive_is_minus_one_but_insufficient_data_is_null() -> None:
    sessions = _sessions(67)
    inactive = compute_tenth_batch_daily_factors(
        _bars(
            sessions=sessions,
            closes=_closes_from_delta7([-1.0] * 60),
            amounts=[100.0] * 67,
        ),
        sessions=sessions,
    )
    assert inactive.tail(1).get_column(_FACTOR).item() == -1.0
    assert inactive.head(66).get_column(_FACTOR).null_count() == 66


def test_price_and_amount_gaps_do_not_bridge_strict_session_windows() -> None:
    sessions = _sessions(68)
    bars = _bars(
        sessions=sessions,
        closes=_closes_from_delta7([-1.0] * 61),
    )

    missing_initial = bars.filter(pl.col("trade_date") != sessions[0])
    initial_result = compute_tenth_batch_daily_factors(
        missing_initial,
        sessions=sessions,
    )
    assert initial_result.filter(
        pl.col("trade_date") == sessions[66]
    ).get_column(_FACTOR).item() is None
    assert initial_result.filter(
        pl.col("trade_date") == sessions[67]
    ).get_column(_FACTOR).item() is not None

    amount_gap = bars.with_columns(
        pl.when(pl.col("trade_date") == sessions[55])
        .then(0.0)
        .otherwise(pl.col("amount"))
        .alias("amount")
    )
    amount_result = compute_tenth_batch_daily_factors(
        amount_gap,
        sessions=sessions,
    )
    assert amount_result.tail(1).get_column(_FACTOR).item() is None

    internal_bar_gap = bars.filter(pl.col("trade_date") != sessions[30])
    internal_result = compute_tenth_batch_daily_factors(
        internal_bar_gap,
        sessions=sessions,
    )
    assert internal_result.tail(1).get_column(_FACTOR).item() is None


def test_adjusted_close_not_raw_close_defines_delta7() -> None:
    sessions = _sessions(67)
    adjusted = _closes_from_delta7([-1.0] * 60)
    raw_closes = [1.0] * 67
    result = compute_tenth_batch_daily_factors(
        _bars(
            sessions=sessions,
            closes=raw_closes,
            amounts=[100.0] * 66 + [200.0],
            adj_factors=adjusted,
        ),
        sessions=sessions,
    )
    assert result.tail(1).get_column(_FACTOR).item() == pytest.approx(0.5)


def test_duplicate_calendar_escape_and_session_identity_fail_closed() -> None:
    sessions = _sessions(67)
    bars = _bars(
        sessions=sessions,
        closes=_closes_from_delta7([-1.0] * 60),
    )
    duplicate = pl.concat(
        [bars, bars.tail(1).with_columns(pl.lit("other").alias("source"))]
    )
    with pytest.raises(ValueError, match="one source per symbol-date"):
        compute_tenth_batch_daily_factors(duplicate, sessions=sessions)
    with pytest.raises(ValueError, match="outside the session calendar"):
        compute_tenth_batch_daily_factors(bars, sessions=sessions[:-1])
    with pytest.raises(ValueError, match="invalid tenth-batch factor request"):
        compute_tenth_batch_daily_factors(bars, sessions=tuple(reversed(sessions)))
    with pytest.raises(ValueError, match="invalid tenth-batch factor request"):
        compute_tenth_batch_daily_factors(bars, sessions=(sessions[0], sessions[0]))


@pytest.mark.parametrize(
    ("column", "value"),
    (
        ("close", True),
        ("amount", True),
        ("adj_factor", True),
        ("close", float("nan")),
        ("amount", float("inf")),
        ("adj_factor", float("-inf")),
    ),
    ids=(
        "boolean-close",
        "boolean-amount",
        "boolean-adjustment",
        "nan-close",
        "infinite-amount",
        "negative-infinite-adjustment",
    ),
)
def test_boolean_nan_and_infinity_sources_fail_closed(
    column: str,
    value: object,
) -> None:
    sessions = _sessions(67)
    bars = _bars(
        sessions=sessions,
        closes=_closes_from_delta7([-1.0] * 60),
    ).with_columns(pl.lit(value).alias(column))
    with pytest.raises(ValueError):
        compute_tenth_batch_daily_factors(bars, sessions=sessions)


@pytest.mark.parametrize(("column", "value"), (("close", 0.0), ("adj_factor", 0.0)))
def test_non_positive_close_and_adjustment_fail_schema(
    column: str,
    value: float,
) -> None:
    sessions = _sessions(67)
    bars = _bars(
        sessions=sessions,
        closes=_closes_from_delta7([-1.0] * 60),
    ).with_columns(pl.lit(value).alias(column))
    with pytest.raises(ValueError):
        compute_tenth_batch_daily_factors(bars, sessions=sessions)


def test_non_positive_amount_is_local_null_and_product_overflow_is_rejected() -> None:
    sessions = _sessions(67)
    zero_amount = _bars(
        sessions=sessions,
        closes=_closes_from_delta7([-1.0] * 60),
        amounts=[100.0] * 66 + [0.0],
    )
    result = compute_tenth_batch_daily_factors(zero_amount, sessions=sessions)
    assert result.tail(1).get_column(_FACTOR).item() is None

    overflow_sessions = _sessions(1)
    overflow = _bars(
        sessions=overflow_sessions,
        closes=[1.0e308],
        amounts=[1.0],
        adj_factors=[1.0e308],
    )
    with pytest.raises(ValueError, match="adjusted-close arithmetic is non-finite"):
        compute_tenth_batch_daily_factors(overflow, sessions=overflow_sessions)


def test_symbols_input_order_and_output_keys_are_isolated_and_canonical() -> None:
    sessions = _sessions(68)
    bars = _bars(
        sessions=sessions,
        closes=_closes_from_delta7([-1.0] * 61),
        symbols=("600002.SH", "600001.SH"),
    )
    bars = bars.filter(
        ~(
            (pl.col("symbol") == "600001.SH")
            & (pl.col("trade_date") == sessions[0])
        )
    )
    result = compute_tenth_batch_daily_factors(bars, sessions=sessions)
    reversed_result = compute_tenth_batch_daily_factors(
        bars.reverse(),
        sessions=sessions,
    )
    assert result.equals(reversed_result, null_equal=True)
    assert result.select("symbol", "trade_date").is_sorted("symbol", "trade_date")
    assert result.height == bars.select("symbol", "trade_date").unique().height
    assert result.select("symbol", "trade_date").equals(
        bars.select("symbol", "trade_date").sort("symbol", "trade_date")
    )

    first = result.filter(pl.col("symbol") == "600001.SH")
    second = result.filter(pl.col("symbol") == "600002.SH")
    assert first.filter(
        pl.col("trade_date") == sessions[66]
    ).get_column(_FACTOR).item() is None
    assert second.filter(
        pl.col("trade_date") == sessions[66]
    ).get_column(_FACTOR).item() is not None
