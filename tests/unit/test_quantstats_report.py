import datetime as dt

import polars as pl
import pytest

from quant.reporting.quantstats_report import returns_by_strategy


def test_returns_by_strategy_converts_nav_without_cross_strategy_leakage() -> None:
    nav = pl.DataFrame({
        "strategy": ["a", "a", "b", "b"],
        "date": [
            dt.date(2026, 1, 1), dt.date(2026, 1, 2),
            dt.date(2026, 1, 1), dt.date(2026, 1, 2),
        ],
        "unit_nav": [1.0, 1.1, 1.0, 0.9],
    })
    result = returns_by_strategy(nav)
    assert result["a"].iloc[0] == pytest.approx(0.1)
    assert result["b"].iloc[0] == pytest.approx(-0.1)
