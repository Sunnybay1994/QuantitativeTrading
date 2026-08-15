from __future__ import annotations

import calendar
import datetime as dt

import polars as pl
import pytest
from pandera.errors import SchemaError

from quant.factors.liquidity import (
    AMIHUD_FACTOR_NAMES,
    LIQUIDITY_FACTOR_NAMES,
    LIQUIDITY_FACTOR_SPECS,
    TURNOVER_FACTOR_NAMES,
    compute_monthly_amihud_illiquidity,
    compute_monthly_free_float_turnover_factors,
)


def _bar(day: dt.date, *, index: int, amount: float = 1_000_000.0) -> dict[str, object]:
    price = 100.0 * 1.01**index
    return {
        "symbol": "000001.SZ",
        "trade_date": day,
        "open": price,
        "high": price,
        "low": price,
        "close": price,
        "volume": 100_000.0,
        "amount": amount,
        "adj_factor": 1.0,
        "source": "tushare",
    }


def _daily_basic(day: dt.date, *, turnover_rate_free: float | None) -> dict[str, object]:
    return {
        "symbol": "000001.SZ",
        "trade_date": day,
        "close": 10.0,
        "turnover_rate": 1.0,
        "turnover_rate_free": turnover_rate_free,
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
        "total_market_value": 100_000_000.0,
        "circulating_market_value": 80_000_000.0,
        "source": "tushare",
    }


def _months() -> tuple[dt.date, ...]:
    return tuple(
        dt.date(year, month, calendar.monthrange(year, month)[1])
        for year, month in (
            *((2024, month) for month in range(1, 13)),
            (2025, 1),
        )
    )


def test_catalog_and_hand_computed_amihud_are_frozen() -> None:
    assert tuple(spec.name for spec in LIQUIDITY_FACTOR_SPECS) == LIQUIDITY_FACTOR_NAMES
    assert AMIHUD_FACTOR_NAMES + TURNOVER_FACTOR_NAMES == LIQUIDITY_FACTOR_NAMES
    sessions = tuple(dt.date(2024, 1, day) for day in range(1, 17))
    bars = pl.DataFrame([_bar(day, index=index) for index, day in enumerate(sessions)])

    result = compute_monthly_amihud_illiquidity(
        bars,
        sessions=sessions,
        signal_dates=(sessions[-1],),
        candidate_symbols=("000001.SZ", "000002.SZ"),
    )

    first = result.filter(pl.col("symbol") == "000001.SZ")
    missing = result.filter(pl.col("symbol") == "000002.SZ")
    assert first.get_column("amihud_valid_days").item() == 15
    assert first.get_column("amihud_illiquidity_monthly").item() == pytest.approx(0.01)
    assert missing.select("amihud_valid_days", "amihud_illiquidity_monthly").row(0) == (
        0,
        None,
    )


def test_amihud_rejects_gap_and_is_adjustment_invariant() -> None:
    sessions = tuple(dt.date(2024, 1, day) for day in range(1, 17))
    rows = [_bar(day, index=index) for index, day in enumerate(sessions)]
    original = pl.DataFrame(rows)
    adjusted = original.with_columns(
        (pl.col("close") / 2.0).alias("close"),
        (pl.col("open") / 2.0).alias("open"),
        (pl.col("high") / 2.0).alias("high"),
        (pl.col("low") / 2.0).alias("low"),
        pl.lit(2.0).alias("adj_factor"),
    )
    kwargs = {
        "sessions": sessions,
        "signal_dates": (sessions[-1],),
        "candidate_symbols": ("000001.SZ",),
    }
    assert compute_monthly_amihud_illiquidity(
        original, **kwargs
    ).get_column("amihud_illiquidity_monthly").item() == pytest.approx(
        compute_monthly_amihud_illiquidity(adjusted, **kwargs)
        .get_column("amihud_illiquidity_monthly")
        .item()
    )

    missing_session = original.filter(pl.col("trade_date") != sessions[7])
    gap_result = compute_monthly_amihud_illiquidity(missing_session, **kwargs)
    assert gap_result.get_column("amihud_valid_days").item() == 13
    assert gap_result.get_column("amihud_illiquidity_monthly").item() is None


def test_zero_amount_is_excluded_without_epsilon() -> None:
    sessions = tuple(dt.date(2024, 1, day) for day in range(1, 17))
    bars = pl.DataFrame(
        [
            _bar(day, index=index, amount=0.0 if index == 8 else 1_000_000.0)
            for index, day in enumerate(sessions)
        ]
    )
    result = compute_monthly_amihud_illiquidity(
        bars,
        sessions=sessions,
        signal_dates=(sessions[-1],),
        candidate_symbols=("000001.SZ",),
    )
    assert result.get_column("amihud_valid_days").item() == 14
    assert result.get_column("amihud_illiquidity_monthly").item() is None


def test_turnover_level_and_prior_twelve_month_anomaly_are_exact() -> None:
    signals = _months()
    rows: list[dict[str, object]] = []
    for month_index, signal in enumerate(signals, start=1):
        for day in range(1, 16):
            rows.append(
                _daily_basic(
                    dt.date(signal.year, signal.month, day),
                    turnover_rate_free=float(month_index),
                )
            )
    result = compute_monthly_free_float_turnover_factors(
        pl.DataFrame(rows),
        signal_dates=signals,
        candidate_symbols=("000001.SZ", "000002.SZ"),
    )

    current = result.filter(
        (pl.col("symbol") == "000001.SZ") & (pl.col("trade_date") == signals[-1])
    )
    assert current.get_column("free_float_turnover_valid_days").item() == 15
    assert current.get_column("free_float_turnover_level_monthly").item() == pytest.approx(
        0.13
    )
    assert current.get_column("free_float_turnover_abnormal_12m").item() == pytest.approx(
        1.0
    )
    assert (
        result.filter(pl.col("symbol") == "000001.SZ")
        .head(12)
        .get_column("free_float_turnover_abnormal_12m")
        .null_count()
        == 12
    )
    assert result.filter(pl.col("symbol") == "000002.SZ").select(
        pl.col("free_float_turnover_level_monthly").is_null().all(),
        pl.col("free_float_turnover_abnormal_12m").is_null().all(),
    ).row(0) == (True, True)


def test_missing_turnover_month_breaks_level_and_future_anomaly() -> None:
    signals = _months()
    rows: list[dict[str, object]] = []
    for month_index, signal in enumerate(signals, start=1):
        day_count = 14 if month_index == 6 else 15
        for day in range(1, day_count + 1):
            rows.append(
                _daily_basic(
                    dt.date(signal.year, signal.month, day),
                    turnover_rate_free=float(month_index),
                )
            )
    result = compute_monthly_free_float_turnover_factors(
        pl.DataFrame(rows),
        signal_dates=signals,
        candidate_symbols=("000001.SZ",),
    )
    invalid = result.filter(pl.col("trade_date") == signals[5])
    current = result.filter(pl.col("trade_date") == signals[-1])
    assert invalid.get_column("free_float_turnover_valid_days").item() == 14
    assert invalid.get_column("free_float_turnover_level_monthly").item() is None
    assert current.get_column("free_float_turnover_abnormal_12m").item() is None


def test_row_order_is_irrelevant_and_duplicate_keys_are_rejected() -> None:
    signals = _months()
    rows = [
        _daily_basic(dt.date(signal.year, signal.month, day), turnover_rate_free=1.0)
        for signal in signals
        for day in range(1, 16)
    ]
    frame = pl.DataFrame(rows)
    kwargs = {"signal_dates": signals, "candidate_symbols": ("000001.SZ",)}
    assert compute_monthly_free_float_turnover_factors(
        frame, **kwargs
    ).equals(compute_monthly_free_float_turnover_factors(frame.reverse(), **kwargs))
    with pytest.raises(SchemaError, match="symbol_date_source_unique"):
        compute_monthly_free_float_turnover_factors(
            pl.concat([frame, frame.head(1)]), **kwargs
        )


def test_missing_calendar_month_is_not_treated_as_twelve_month_history() -> None:
    signals = _months()
    skipped = signals[:5] + signals[6:]
    rows = [
        _daily_basic(dt.date(signal.year, signal.month, day), turnover_rate_free=1.0)
        for signal in skipped
        for day in range(1, 16)
    ]
    with pytest.raises(ValueError, match="invalid monthly liquidity factor schedule"):
        compute_monthly_free_float_turnover_factors(
            pl.DataFrame(rows),
            signal_dates=skipped,
            candidate_symbols=("000001.SZ",),
        )
