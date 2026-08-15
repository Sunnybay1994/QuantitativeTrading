from __future__ import annotations

import datetime as dt
import math
import statistics

import polars as pl
import pytest
from pandera.errors import SchemaError

from quant.factors import (
    SECOND_BATCH_FACTOR_NAMES,
    compute_second_batch_daily_factors,
)


def _bars(*, prices: list[float], volumes: list[float]) -> pl.DataFrame:
    dates = [dt.date(2024, 1, 1) + dt.timedelta(days=index) for index in range(len(prices))]
    return pl.DataFrame(
        {
            "symbol": ["600000.SH"] * len(prices),
            "trade_date": dates,
            "open": prices,
            "high": [value + 1.0 for value in prices],
            "low": [value - 1.0 for value in prices],
            "close": prices,
            "volume": volumes,
            "amount": [price * volume for price, volume in zip(prices, volumes, strict=True)],
            "adj_factor": [1.0] * len(prices),
            "source": ["fixture"] * len(prices),
        }
    )


def test_second_batch_formulas_match_hand_calculation() -> None:
    prices = [10.0 + index * 0.4 + (index % 3) * 0.1 for index in range(25)]
    volumes = [1000.0 + index * 37.0 + (index % 4) * 11.0 for index in range(25)]

    factors = compute_second_batch_daily_factors(_bars(prices=prices, volumes=volumes))

    ma_expected = statistics.mean(prices[:20]) / prices[19]
    corr_expected = statistics.correlation(
        prices[:20], [math.log1p(value) for value in volumes[:20]]
    )
    weighted = [
        abs(prices[index] / prices[index - 1] - 1.0) * volumes[index]
        for index in range(1, 21)
    ]
    wvma_expected = statistics.stdev(weighted) / (statistics.mean(weighted) + 1e-12)

    assert factors.item(19, "alpha158_ma20") == pytest.approx(ma_expected)
    assert factors.item(19, "alpha158_corr20") == pytest.approx(corr_expected)
    assert factors.item(20, "alpha158_wvma20") == pytest.approx(wvma_expected)
    assert tuple(name for name in SECOND_BATCH_FACTOR_NAMES) == (
        "alpha158_ma20",
        "alpha158_corr20",
        "alpha158_wvma20",
    )


def test_ma20_uses_adjusted_close_across_split() -> None:
    prices = [20.0 + index for index in range(20)]
    volumes = [1000.0 + index for index in range(20)]
    original = _bars(prices=prices, volumes=volumes)
    split = original.with_columns(
        pl.when(pl.int_range(pl.len()) >= 10)
        .then(pl.col("open") / 2)
        .otherwise(pl.col("open"))
        .alias("open"),
        pl.when(pl.int_range(pl.len()) >= 10)
        .then(pl.col("high") / 2)
        .otherwise(pl.col("high"))
        .alias("high"),
        pl.when(pl.int_range(pl.len()) >= 10)
        .then(pl.col("low") / 2)
        .otherwise(pl.col("low"))
        .alias("low"),
        pl.when(pl.int_range(pl.len()) >= 10)
        .then(pl.col("close") / 2)
        .otherwise(pl.col("close"))
        .alias("close"),
        pl.when(pl.int_range(pl.len()) >= 10)
        .then(2.0)
        .otherwise(1.0)
        .alias("adj_factor"),
    )

    before = compute_second_batch_daily_factors(original)
    after = compute_second_batch_daily_factors(split)

    assert after.item(19, "alpha158_ma20") == pytest.approx(
        before.item(19, "alpha158_ma20")
    )


def test_second_batch_rejects_duplicate_symbol_date() -> None:
    bars = _bars(prices=[10.0] * 20, volumes=[1000.0] * 20)
    duplicate = pl.concat([bars, bars.head(1)])

    with pytest.raises(SchemaError):
        compute_second_batch_daily_factors(duplicate)
