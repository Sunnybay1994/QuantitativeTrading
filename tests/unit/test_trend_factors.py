import datetime as dt
import math

import polars as pl

from quant.factors import compute_trend_factors, compute_trend_factors_from_prices


def bars(symbol: str, *, daily_log_return: float, days: int = 121) -> pl.DataFrame:
    dates = [dt.date(2025, 1, 1) + dt.timedelta(days=index) for index in range(days)]
    closes = [10.0 * math.exp(daily_log_return * index) for index in range(days)]
    return pl.DataFrame({
        "symbol": [symbol] * days,
        "trade_date": dates,
        "open": closes,
        "high": closes,
        "low": closes,
        "close": closes,
        "volume": [1000.0] * days,
        "amount": [10000.0] * days,
        "adj_factor": [1.0] * days,
        "source": ["fixture"] * days,
    })


def test_trend_factors_distinguish_rising_and_falling_prices() -> None:
    frame = pl.concat([
        bars("510300.SH", daily_log_return=0.001),
        bars("159919.SZ", daily_log_return=-0.001),
    ])
    as_of = dt.date(2025, 5, 1)
    result = compute_trend_factors(frame, as_of=as_of, source="fixture")
    values = {
        (row["symbol"], row["factor"]): row["value"]
        for row in result.iter_rows(named=True)
    }
    assert values[("510300.SH", "momentum_120")] > 0
    assert values[("510300.SH", "regression_slope_r2_60")] > 0
    assert values[("159919.SZ", "momentum_120")] < 0
    assert values[("159919.SZ", "regression_slope_r2_60")] < 0


def test_stale_symbol_does_not_reuse_old_signal() -> None:
    frame = bars("510300.SH", daily_log_return=0.001, days=120)
    result = compute_trend_factors(
        frame, as_of=dt.date(2025, 5, 1), source="fixture"
    )
    assert result.get_column("value").null_count() == result.height


def test_hfq_research_prices_use_same_factor_core() -> None:
    raw = bars("510300.SH", daily_log_return=0.001)
    prices = raw.select(
        "symbol",
        "trade_date",
        pl.col("close").alias("adjusted_close"),
        pl.lit("HFQ").alias("adjustment_method"),
        pl.lit("akshare").alias("source"),
    )
    result = compute_trend_factors_from_prices(
        prices, as_of=dt.date(2025, 5, 1), source="akshare"
    )
    momentum = result.filter(pl.col("factor") == "momentum_120").item(0, "value")
    assert momentum > 0
