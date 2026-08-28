from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from quant.factors.classic_sixth_batch import (
    SIXTH_BATCH_FACTOR_NAMES,
    SIXTH_BATCH_FACTOR_SPECS,
    compute_sixth_batch_daily_factors,
)


def _sessions(count: int) -> tuple[dt.date, ...]:
    start = dt.date(2025, 1, 2)
    return tuple(start + dt.timedelta(days=index) for index in range(count))


def _bars(
    *,
    sessions: tuple[dt.date, ...],
    opens: list[float] | None = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    closes: list[float] | None = None,
    volumes: list[float] | None = None,
    amounts: list[float] | None = None,
    adj_factors: list[float] | None = None,
    symbols: tuple[str, ...] = ("600001.SH",),
) -> pl.DataFrame:
    count = len(sessions)
    open_values = opens or [100.0 + index for index in range(count)]
    close_values = closes or [value + 0.5 for value in open_values]
    high_values = highs or [max(open_values[index], close_values[index]) + 1.0 for index in range(count)]
    low_values = lows or [min(open_values[index], close_values[index]) - 1.0 for index in range(count)]
    volume_values = volumes or [1_000.0 + 10.0 * index for index in range(count)]
    amount_values = amounts or [close_values[index] * volume_values[index] for index in range(count)]
    factor_values = adj_factors or [1.0] * count
    rows: list[dict[str, object]] = []
    for symbol in symbols:
        for index, trade_date in enumerate(sessions):
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "open": open_values[index],
                    "high": high_values[index],
                    "low": low_values[index],
                    "close": close_values[index],
                    "volume": volume_values[index],
                    "amount": amount_values[index],
                    "adj_factor": factor_values[index],
                    "source": "fixture",
                }
            )
    return pl.DataFrame(rows)


def test_public_identity_and_exact_wide_output_contract() -> None:
    assert SIXTH_BATCH_FACTOR_NAMES == (
        "alpha101_006",
        "alpha101_012",
        "alpha101_041",
    )
    assert tuple(spec.name for spec in SIXTH_BATCH_FACTOR_SPECS) == SIXTH_BATCH_FACTOR_NAMES

    sessions = _sessions(12)
    result = compute_sixth_batch_daily_factors(
        _bars(sessions=sessions),
        sessions=sessions,
    )

    assert result.columns == ["symbol", "trade_date", *SIXTH_BATCH_FACTOR_NAMES]
    assert result.schema == {
        "symbol": pl.String,
        "trade_date": pl.Date,
        "alpha101_006": pl.Float64,
        "alpha101_012": pl.Float64,
        "alpha101_041": pl.Float64,
    }
    assert result.select("symbol", "trade_date").height == len(sessions)
    assert result.select("symbol", "trade_date").is_sorted("symbol", "trade_date")


def test_alpha006_uses_exact_ten_sessions_adjusted_open_and_raw_volume() -> None:
    sessions = _sessions(11)
    adjusted_opens = [100.0 + index for index in range(len(sessions))]
    factors = [1.0] * 5 + [2.0] * 6
    raw_opens = [adjusted_opens[index] / factors[index] for index in range(len(sessions))]
    volumes = [2_000.0 - 10.0 * index for index in range(len(sessions))]
    result = compute_sixth_batch_daily_factors(
        _bars(
            sessions=sessions,
            opens=raw_opens,
            closes=raw_opens,
            volumes=volumes,
            adj_factors=factors,
        ),
        sessions=sessions,
    )

    assert result.head(9).get_column("alpha101_006").null_count() == 9
    assert result.tail(1).get_column("alpha101_006").item() == pytest.approx(1.0)

    short_sessions = _sessions(9)
    short = compute_sixth_batch_daily_factors(
        _bars(sessions=short_sessions),
        sessions=short_sessions,
    )
    assert short.get_column("alpha101_006").null_count() == len(short_sessions)


def test_alpha006_gap_and_zero_variance_are_null_without_cross_gap_bridging() -> None:
    sessions = _sessions(12)
    missing = sessions[5]
    gap_bars = _bars(sessions=sessions).filter(pl.col("trade_date") != missing)
    gap_result = compute_sixth_batch_daily_factors(gap_bars, sessions=sessions)
    assert gap_result.tail(1).get_column("alpha101_006").item() is None

    flat_open = _bars(sessions=_sessions(10), opens=[100.0] * 10)
    flat_result = compute_sixth_batch_daily_factors(
        flat_open,
        sessions=_sessions(10),
    )
    assert flat_result.tail(1).get_column("alpha101_006").item() is None

    flat_volume_sessions = _sessions(10)
    flat_volume = _bars(
        sessions=flat_volume_sessions,
        volumes=[1_000.0] * len(flat_volume_sessions),
    )
    flat_volume_result = compute_sixth_batch_daily_factors(
        flat_volume,
        sessions=flat_volume_sessions,
    )
    assert flat_volume_result.tail(1).get_column("alpha101_006").item() is None
    assert flat_volume_result.tail(9).get_column("alpha101_012").null_count() == 0
    assert flat_volume_result.get_column("alpha101_041").null_count() == 0

    zero_volume = _bars(sessions=sessions).with_columns(
        pl.when(pl.col("trade_date") == sessions[5])
        .then(0.0)
        .otherwise(pl.col("volume"))
        .alias("volume")
    )
    zero_volume_result = compute_sixth_batch_daily_factors(
        zero_volume,
        sessions=sessions,
    )
    assert zero_volume_result.tail(1).get_column("alpha101_006").item() is None


def test_alpha012_uses_signed_volume_delta_and_adjusted_price_difference() -> None:
    sessions = _sessions(4)
    factors = [2.0] * len(sessions)
    result = compute_sixth_batch_daily_factors(
        _bars(
            sessions=sessions,
            opens=[50.0, 55.0, 50.0, 60.0],
            closes=[50.0, 55.0, 50.0, 60.0],
            volumes=[100.0, 200.0, 200.0, 100.0],
            adj_factors=factors,
        ),
        sessions=sessions,
    )

    assert result.get_column("alpha101_012").to_list() == [None, -10.0, 0.0, 20.0]


def test_alpha012_zero_volume_invalidates_only_the_affected_pairs() -> None:
    sessions = _sessions(4)
    result = compute_sixth_batch_daily_factors(
        _bars(
            sessions=sessions,
            closes=[100.0, 110.0, 120.0, 130.0],
            volumes=[100.0, 0.0, 100.0, 110.0],
        ),
        sessions=sessions,
    )

    assert result.get_column("alpha101_012").to_list() == [None, None, None, -10.0]


def test_alpha041_uses_raw_cny_units_and_amount_div_volume_without_adjustment() -> None:
    sessions = _sessions(1)
    result = compute_sixth_batch_daily_factors(
        _bars(
            sessions=sessions,
            opens=[5.0],
            highs=[9.0],
            lows=[4.0],
            closes=[8.0],
            volumes=[10.0],
            amounts=[50.0],
            adj_factors=[10.0],
        ),
        sessions=sessions,
    )
    assert result.get_column("alpha101_041").item() == pytest.approx(1.0)

    equal_vwap = compute_sixth_batch_daily_factors(
        _bars(
            sessions=sessions,
            opens=[5.0],
            highs=[9.0],
            lows=[4.0],
            closes=[8.0],
            volumes=[10.0],
            amounts=[60.0],
            adj_factors=[100.0],
        ),
        sessions=sessions,
    )
    assert equal_vwap.get_column("alpha101_041").item() == pytest.approx(0.0)


def test_alpha041_non_positive_vwap_denominator_is_row_null() -> None:
    sessions = _sessions(2)
    result = compute_sixth_batch_daily_factors(
        _bars(
            sessions=sessions,
            volumes=[10.0, 0.0],
            amounts=[0.0, 20.0],
        ),
        sessions=sessions,
    )
    assert result.get_column("alpha101_041").to_list() == [None, None]


def test_missing_session_does_not_contaminate_another_symbol() -> None:
    sessions = _sessions(11)
    bars = _bars(sessions=sessions, symbols=("600001.SH", "600002.SH"))
    bars = bars.filter(
        ~(
            (pl.col("symbol") == "600001.SH")
            & (pl.col("trade_date") == sessions[5])
        )
    )
    result = compute_sixth_batch_daily_factors(bars, sessions=sessions)

    first = result.filter(pl.col("symbol") == "600001.SH")
    second = result.filter(pl.col("symbol") == "600002.SH")
    assert first.tail(1).get_column("alpha101_006").item() is None
    assert second.tail(1).get_column("alpha101_006").item() is not None


@pytest.mark.parametrize(
    ("column", "value"),
    (
        ("volume", True),
        ("amount", float("nan")),
        ("close", float("inf")),
        ("adj_factor", float("-inf")),
    ),
    ids=("boolean", "nan", "positive-infinity", "negative-infinity"),
)
def test_boolean_nan_and_infinity_source_values_fail_closed(
    column: str, value: object
) -> None:
    sessions = _sessions(3)
    bars = _bars(sessions=sessions).with_columns(pl.lit(value).alias(column))

    with pytest.raises(ValueError):
        compute_sixth_batch_daily_factors(bars, sessions=sessions)


def test_overflow_and_negative_schema_values_fail_closed() -> None:
    sessions = _sessions(1)
    overflow = _bars(
        sessions=sessions,
        opens=[1.0e308],
        highs=[1.0e308],
        lows=[1.0e308],
        closes=[1.0e308],
        volumes=[1.0],
        amounts=[1.0],
    )
    with pytest.raises(ValueError, match="factor arithmetic is non-finite"):
        compute_sixth_batch_daily_factors(overflow, sessions=sessions)

    negative = _bars(sessions=sessions, volumes=[-1.0])
    with pytest.raises(ValueError, match="fail Bar1dSchema validation"):
        compute_sixth_batch_daily_factors(negative, sessions=sessions)


def test_duplicate_key_calendar_escape_and_session_order_fail_closed() -> None:
    sessions = _sessions(3)
    bars = _bars(sessions=sessions)
    duplicate = pl.concat(
        [bars, bars.tail(1).with_columns(pl.lit("other").alias("source"))]
    )
    with pytest.raises(ValueError, match="one source per symbol-date"):
        compute_sixth_batch_daily_factors(duplicate, sessions=sessions)

    with pytest.raises(ValueError, match="outside the session calendar"):
        compute_sixth_batch_daily_factors(bars, sessions=sessions[:-1])
    with pytest.raises(ValueError, match="invalid sixth-batch factor request"):
        compute_sixth_batch_daily_factors(bars, sessions=tuple(reversed(sessions)))
    with pytest.raises(ValueError, match="invalid sixth-batch factor request"):
        compute_sixth_batch_daily_factors(bars, sessions=(sessions[0], sessions[0]))


def test_input_row_order_is_canonical_and_only_input_keys_are_returned() -> None:
    sessions = _sessions(12)
    bars = _bars(sessions=sessions, symbols=("600002.SH", "600001.SH"))
    result = compute_sixth_batch_daily_factors(bars, sessions=sessions)
    reversed_result = compute_sixth_batch_daily_factors(
        bars.reverse(),
        sessions=sessions,
    )

    assert result.equals(reversed_result, null_equal=True)
    assert result.height == bars.select("symbol", "trade_date").unique().height
    assert set(result.columns) == {
        "symbol",
        "trade_date",
        "alpha101_006",
        "alpha101_012",
        "alpha101_041",
    }
