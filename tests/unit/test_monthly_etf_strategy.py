import calendar
import datetime as dt

import polars as pl
import pytest

from quant.strategies.monthly_etf import MonthlyEtfStrategy


def monthly_prices(values):
    rows = []
    for symbol, prices in values.items():
        for offset, price in enumerate(prices):
            year, month = 2024 + offset // 12, offset % 12 + 1
            rows.append({"symbol": symbol, "trade_date": dt.date(year, month, calendar.monthrange(year, month)[1]),
                         "adjusted_close": float(price)})
    return pl.DataFrame(rows)


def test_sma_keeps_inactive_sleeve_in_cash_and_uses_completed_month():
    prices = monthly_prices({"A": [10] * 9 + [11, 1000], "B": [11] * 9 + [10, 1]})
    strategy = MonthlyEtfStrategy(("A", "B"), "sma", 10, top_k=1)
    result = strategy.target_weights(dt.date(2024, 10, 31), prices)
    assert dict(result.select("symbol", "weight").iter_rows()) == {"A": .5, "B": 0.}
    flat = prices.with_columns(pl.lit(10.).alias("adjusted_close"))
    assert strategy.target_weights(dt.date(2024, 10, 31), flat)["weight"].sum() == 0.


def test_relative_momentum_skips_last_month_and_ignores_future_prices():
    prices = monthly_prices({"A": [100] + [110] * 11 + [1000, 1],
                             "B": [100] + [120] * 11 + [1, 1000]})
    strategy = MonthlyEtfStrategy(("A", "B"), "relative_momentum", 12, skip_months=1, top_k=1)
    result = strategy.target_weights(dt.date(2025, 1, 31), prices)
    assert dict(result.select("symbol", "weight").iter_rows()) == {"A": 0., "B": 1.}
    missing = prices.filter(pl.col("trade_date") != dt.date(2024, 6, 30))
    with pytest.raises(ValueError, match="Incomplete monthly price"):
        strategy.target_weights(dt.date(2025, 1, 31), missing)
