from __future__ import annotations

import datetime as dt
import math
import statistics

import polars as pl
import pytest
from pandera.errors import SchemaError

from quant.factors import (
    THIRD_BATCH_FACTOR_NAMES,
    compute_third_batch_daily_factors,
)


def test_third_batch_formulas_match_hand_calculation() -> None:
    prices = [10.0 + index * 0.3 + (index % 4) * 0.07 for index in range(25)]
    volumes = [1000.0 + index * 31.0 + (index % 5) * 13.0 for index in range(25)]

    factors = compute_third_batch_daily_factors(
        _bars(prices=prices, volumes=volumes)
    )

    x = list(range(20))
    slope, _ = statistics.linear_regression(x, prices[:20])
    beta_expected = slope / prices[19]
    rsqr_expected = statistics.correlation(x, prices[:20]) ** 2
    price_ratios = [prices[index] / prices[index - 1] for index in range(1, 21)]
    volume_ratios = [
        math.log(volumes[index] / volumes[index - 1] + 1.0)
        for index in range(1, 21)
    ]
    cord_expected = statistics.correlation(price_ratios, volume_ratios)
    changes = [prices[index] - prices[index - 1] for index in range(1, 21)]
    sumd_expected = sum(changes) / (sum(abs(value) for value in changes) + 1e-12)

    assert factors.item(19, "alpha158_beta20") == pytest.approx(beta_expected)
    assert factors.item(19, "alpha158_rsqr20") == pytest.approx(rsqr_expected)
    assert factors.item(20, "alpha158_cord20") == pytest.approx(cord_expected)
    assert factors.item(20, "alpha158_sumd20") == pytest.approx(sumd_expected)
    assert THIRD_BATCH_FACTOR_NAMES == (
        "alpha158_beta20",
        "alpha158_rsqr20",
        "alpha158_cord20",
        "alpha158_sumd20",
    )


def test_third_batch_price_features_use_adjusted_close() -> None:
    prices = [20.0 + index * 0.4 + (index % 3) * 0.1 for index in range(25)]
    volumes = [1000.0 + index * 17.0 for index in range(25)]
    original = _bars(prices=prices, volumes=volumes)
    split = original.with_columns(
        *[
            pl.when(pl.int_range(pl.len()) >= 10)
            .then(pl.col(column) / 2)
            .otherwise(pl.col(column))
            .alias(column)
            for column in ("open", "high", "low", "close")
        ],
        pl.when(pl.int_range(pl.len()) >= 10)
        .then(2.0)
        .otherwise(1.0)
        .alias("adj_factor"),
    )

    before = compute_third_batch_daily_factors(original)
    after = compute_third_batch_daily_factors(split)

    for name in ("alpha158_beta20", "alpha158_rsqr20", "alpha158_sumd20"):
        assert after.item(20, name) == pytest.approx(before.item(20, name))


def test_third_batch_rejects_duplicate_symbol_date() -> None:
    bars = _bars(prices=[10.0] * 21, volumes=[1000.0] * 21)

    with pytest.raises(SchemaError):
        compute_third_batch_daily_factors(pl.concat([bars, bars.head(1)]))


def _bars(*, prices: list[float], volumes: list[float]) -> pl.DataFrame:
    dates = [
        dt.date(2024, 1, 1) + dt.timedelta(days=index)
        for index in range(len(prices))
    ]
    return pl.DataFrame(
        {
            "symbol": ["600000.SH"] * len(prices),
            "trade_date": dates,
            "open": prices,
            "high": [value + 1.0 for value in prices],
            "low": [value - 1.0 for value in prices],
            "close": prices,
            "volume": volumes,
            "amount": [
                price * volume for price, volume in zip(prices, volumes, strict=True)
            ],
            "adj_factor": [1.0] * len(prices),
            "source": ["fixture"] * len(prices),
        }
    )
