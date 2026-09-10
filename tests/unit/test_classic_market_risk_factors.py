from __future__ import annotations

import datetime as dt
import math
from typing import Any

import polars as pl
import pytest

from quant.factors.classic_market_risk import (
    DOWNSIDE_BETA_NAME,
    MARKET_BETA_CONTROL_NAME,
    REALIZED_VOLATILITY_CONTROL_NAME,
    compute_classic_market_risk_factors,
)


def _market_returns(*, negative_observations: int = 30) -> list[float]:
    negative = [-0.010 - index * 0.0001 for index in range(negative_observations)]
    positive = [
        0.008 + index * 0.00005 for index in range(negative_observations, 60)
    ]
    return negative + positive


def _bars_from_returns(
    symbol: str,
    returns: list[float],
    *,
    slope: float = 1.0,
    intercept: float = 0.0,
    split_after: int | None = None,
) -> pl.DataFrame:
    sessions = [dt.date(2025, 1, 1) + dt.timedelta(days=index) for index in range(61)]
    adjusted_prices = [100.0]
    for value in returns:
        adjusted_prices.append(adjusted_prices[-1] * math.exp(intercept + slope * value))
    rows: list[dict[str, object]] = []
    for index, (trade_date, adjusted_close) in enumerate(
        zip(sessions, adjusted_prices, strict=True)
    ):
        factor = 2.0 if split_after is not None and index >= split_after else 1.0
        raw_close = adjusted_close / factor
        rows.append(
            {
                "symbol": symbol,
                "trade_date": trade_date,
                "open": raw_close,
                "high": raw_close * 1.01,
                "low": raw_close * 0.99,
                "close": raw_close,
                "volume": 1_000_000.0,
                "amount": raw_close * 1_000_000.0,
                "adj_factor": factor,
                "source": "fixture",
            }
        )
    return pl.DataFrame(rows)


def _request(
    *,
    negative_observations: int = 30,
    stock_slope: float = 2.0,
    split_after: int | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame, dict[str, Any]]:
    returns = _market_returns(negative_observations=negative_observations)
    stocks = _bars_from_returns(
        "600001.SH", returns, slope=stock_slope, intercept=0.0003, split_after=split_after
    )
    benchmark = _bars_from_returns("510300.SH", returns)
    return (
        stocks,
        benchmark,
        {
            "sessions": tuple(stocks.get_column("trade_date").to_list()),
            "benchmark_symbol": "510300.SH",
        },
    )


def test_market_risk_factors_match_ols_and_are_row_order_invariant() -> None:
    stocks, benchmark, request = _request()
    result = compute_classic_market_risk_factors(stocks, benchmark, **request)
    shuffled = compute_classic_market_risk_factors(
        stocks.reverse(), benchmark.reverse(), **request
    )

    last = result.tail(1)
    assert last.get_column(DOWNSIDE_BETA_NAME).item() == pytest.approx(2.0)
    assert last.get_column(MARKET_BETA_CONTROL_NAME).item() == pytest.approx(2.0)
    assert last.get_column(REALIZED_VOLATILITY_CONTROL_NAME).item() > 0
    assert result.equals(shuffled, null_equal=True)


def test_exact_down_observation_boundary_and_zero_variance_fail_closed() -> None:
    stocks, benchmark, request = _request(negative_observations=15)
    valid = compute_classic_market_risk_factors(stocks, benchmark, **request)
    assert valid.tail(1).get_column(DOWNSIDE_BETA_NAME).item() == pytest.approx(2.0)

    stocks, benchmark, request = _request(negative_observations=14)
    too_few = compute_classic_market_risk_factors(stocks, benchmark, **request)
    assert too_few.tail(1).get_column(DOWNSIDE_BETA_NAME).item() is None

    flat_down_returns = [-0.01] * 15 + [0.01 + index * 0.0001 for index in range(45)]
    stocks = _bars_from_returns("600001.SH", flat_down_returns, slope=2.0)
    benchmark = _bars_from_returns("510300.SH", flat_down_returns)
    zero_variance = compute_classic_market_risk_factors(
        stocks,
        benchmark,
        sessions=tuple(stocks.get_column("trade_date").to_list()),
        benchmark_symbol="510300.SH",
    )
    assert zero_variance.tail(1).get_column(DOWNSIDE_BETA_NAME).item() is None


def test_missing_session_does_not_create_cross_gap_return() -> None:
    stocks, benchmark, request = _request()
    missing_stock = stocks.filter(pl.col("trade_date") != request["sessions"][30])
    result = compute_classic_market_risk_factors(missing_stock, benchmark, **request)
    assert result.tail(1).get_column(DOWNSIDE_BETA_NAME).item() is None
    assert result.tail(1).get_column(MARKET_BETA_CONTROL_NAME).item() is None

    missing_benchmark = benchmark.filter(
        pl.col("trade_date") != request["sessions"][30]
    )
    result = compute_classic_market_risk_factors(stocks, missing_benchmark, **request)
    assert result.tail(1).get_column(DOWNSIDE_BETA_NAME).item() is None


def test_adjusted_price_split_is_invariant() -> None:
    plain_stock, benchmark, request = _request()
    split_stock, _, _ = _request(split_after=30)
    plain = compute_classic_market_risk_factors(plain_stock, benchmark, **request)
    split = compute_classic_market_risk_factors(split_stock, benchmark, **request)
    assert plain.select(
        DOWNSIDE_BETA_NAME,
        MARKET_BETA_CONTROL_NAME,
        REALIZED_VOLATILITY_CONTROL_NAME,
    ).equals(
        split.select(
            DOWNSIDE_BETA_NAME,
            MARKET_BETA_CONTROL_NAME,
            REALIZED_VOLATILITY_CONTROL_NAME,
        ),
        null_equal=True,
    )


def test_benchmark_identity_and_duplicate_symbol_date_are_rejected() -> None:
    stocks, benchmark, request = _request()
    wrong = benchmark.with_columns(pl.lit("159919.SZ").alias("symbol"))
    with pytest.raises(ValueError, match="benchmark symbol mismatch"):
        compute_classic_market_risk_factors(stocks, wrong, **request)

    duplicate = pl.concat(
        [benchmark, benchmark.tail(1).with_columns(pl.lit("other").alias("source"))]
    )
    with pytest.raises(ValueError, match="one source per symbol-date"):
        compute_classic_market_risk_factors(stocks, duplicate, **request)


def test_monthly_beta_uses_total_returns_without_changing_execution_prices() -> None:
    from quant.research.monthly_low_beta import build_monthly_low_beta

    stocks, benchmark, request = _request()
    prices = benchmark.select('symbol', 'trade_date', pl.col('close').alias('adjusted_close')).with_columns(
        pl.lit('TOTAL_RETURN_DIVIDEND').alias('adjustment_method'))
    ex_date = request['sessions'][30]
    raw = benchmark.with_columns(pl.when(pl.col('trade_date') >= ex_date)
        .then(pl.col(c) * .9).otherwise(pl.col(c)).alias(c) for c in ['open', 'high', 'low', 'close'])
    before = raw.clone()
    selected = request['sessions'][-2:]
    result = build_monthly_low_beta(stocks, raw, prices, sessions=request['sessions'], signal_dates=selected)
    assert result['trade_date'].to_list() == list(selected)
    assert result[MARKET_BETA_CONTROL_NAME][0] is None
    assert result[MARKET_BETA_CONTROL_NAME][1] == pytest.approx(2.)
    assert raw.equals(before)


def test_monthly_market_beta_does_not_require_down_days_or_positive_beta() -> None:
    from quant.research.monthly_low_beta import build_monthly_low_beta

    stocks, benchmark, request = _request(negative_observations=0, stock_slope=-.5)
    prices = benchmark.select('symbol', 'trade_date', pl.col('close').alias('adjusted_close')).with_columns(
        pl.lit('TOTAL_RETURN_DIVIDEND').alias('adjustment_method'))
    result = build_monthly_low_beta(stocks, benchmark, prices, sessions=request['sessions'],
                                    signal_dates=(request['sessions'][-1],))
    assert result[MARKET_BETA_CONTROL_NAME].item() == pytest.approx(-.5)
    with pytest.raises(ValueError, match='Incomplete total-return benchmark'):
        build_monthly_low_beta(stocks, benchmark, prices.head(60), sessions=request['sessions'],
                               signal_dates=(request['sessions'][-1],))


def test_low_beta_preregistration_is_fixed() -> None:
    import tomllib
    from pathlib import Path

    from quant.research.monthly_low_beta import validate_low_beta

    config = tomllib.loads((Path(__file__).resolve().parents[2]
        / 'configs/research/b60_low_market_beta60_20260910.toml').read_text(encoding='utf-8'))
    validate_low_beta(config)
    config['low_beta']['window_sessions'] = 120
    with pytest.raises(ValueError):
        validate_low_beta(config)
    config['low_beta']['window_sessions'] = 60
    config['factors']['directions'] = [1]
    with pytest.raises(ValueError):
        validate_low_beta(config)
