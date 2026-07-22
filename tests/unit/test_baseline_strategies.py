import datetime as dt

import polars as pl

from quant.strategies import EqualWeightStrategy, EtfTrendStrategy


AS_OF = dt.date(2026, 7, 10)


def test_equal_weight_uses_only_available_frozen_candidates() -> None:
    strategy = EqualWeightStrategy(
        candidates=("510300.SH", "159919.SZ", "513100.SH"), cash_buffer=0.1
    )
    result = strategy.target_weights(
        AS_OF,
        pl.DataFrame({
            "symbol": ["510300.SH", "159919.SZ", "000001.SZ"],
            "eligible": [True, False, True],
        }),
    )
    assert result.get_column("symbol").to_list() == ["510300.SH"]
    assert result.get_column("weight").to_list() == [0.9]


def test_etf_trend_filters_negative_absolute_trend_and_keeps_cash() -> None:
    factors = []
    values = {
        "510300.SH": [0.03, 0.08, 0.12, 0.6],
        "159919.SZ": [-0.01, 0.05, 0.10, 0.8],
        "513100.SH": [0.02, 0.04, 0.07, 0.4],
    }
    names = ["momentum_20", "momentum_60", "momentum_120", "regression_slope_r2_60"]
    for symbol, symbol_values in values.items():
        factors.extend({
            "as_of": AS_OF,
            "symbol": symbol,
            "factor": name,
            "value": value,
            "factor_version": "trend_v1",
        } for name, value in zip(names, symbol_values, strict=True))
    strategy = EtfTrendStrategy(candidates=tuple(values), top_k=2, cash_buffer=0.1)
    result = strategy.target_weights(AS_OF, pl.DataFrame(factors))
    assert result.get_column("symbol").to_list() == ["510300.SH", "513100.SH"]
    assert result.get_column("weight").to_list() == [0.45, 0.45]


def test_etf_trend_emits_explicit_zero_targets_when_all_assets_fail() -> None:
    names = ["momentum_20", "momentum_60", "momentum_120", "regression_slope_r2_60"]
    factors = pl.DataFrame([
        {
            "as_of": AS_OF,
            "symbol": "510300.SH",
            "factor": name,
            "value": -0.1,
            "factor_version": "trend_v1",
        }
        for name in names
    ])
    result = EtfTrendStrategy(candidates=("510300.SH",)).target_weights(AS_OF, factors)
    assert result.get_column("symbol").to_list() == ["510300.SH"]
    assert result.get_column("weight").to_list() == [0.0]
