import datetime as dt
import math

import polars as pl
import pytest

from quant.strategies import (
    EqualWeightStrategy,
    EtfTrendStrategy,
    RegimeFilteredEtfTrendStrategy,
)
from quant.portfolio import (
    retain_ranked_target_selection,
    scale_target_weights_to_volatility,
)


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


def test_regime_filtered_etf_trend_matches_base_strategy_when_risk_on() -> None:
    factors = _trend_factors({
        "510300.SH": [0.01, 0.03, 0.05, 0.4],
        "512880.SH": [0.03, 0.06, 0.09, 0.8],
    })
    result = RegimeFilteredEtfTrendStrategy(
        candidates=("510300.SH", "512880.SH"),
        regime_symbol="510300.SH",
        top_k=1,
        cash_buffer=0.1,
    ).target_weights(AS_OF, factors)
    assert result.get_column("symbol").to_list() == ["512880.SH"]
    assert result.get_column("weight").to_list() == [0.9]


def test_regime_filtered_etf_trend_moves_to_cash_when_risk_off() -> None:
    factors = _trend_factors({
        "510300.SH": [-0.01, 0.03, 0.05, 0.4],
        "512880.SH": [0.03, 0.06, 0.09, 0.8],
    })
    result = RegimeFilteredEtfTrendStrategy(
        candidates=("510300.SH", "512880.SH"),
        regime_symbol="510300.SH",
        top_k=1,
        cash_buffer=0.1,
    ).target_weights(AS_OF, factors)
    assert result.get_column("symbol").to_list() == ["510300.SH", "512880.SH"]
    assert result.get_column("weight").to_list() == [0.0, 0.0]


def test_rank_retention_keeps_prior_symbol_inside_explicit_buffer() -> None:
    factors = _trend_factors({
        "510300.SH": [0.01, 0.03, 0.05, 0.9],
        "512880.SH": [0.03, 0.06, 0.09, 0.8],
        "512170.SH": [0.02, 0.05, 0.08, 0.7],
        "515790.SH": [0.01, 0.04, 0.07, 0.6],
    })
    common = {
        "candidates": ("510300.SH", "512880.SH", "512170.SH", "515790.SH"),
        "regime_symbol": "510300.SH",
        "cash_buffer": 0.1,
    }
    current = RegimeFilteredEtfTrendStrategy(top_k=2, **common).target_weights(
        AS_OF, factors
    )
    band = RegimeFilteredEtfTrendStrategy(top_k=3, **common).target_weights(
        AS_OF, factors
    )

    result = retain_ranked_target_selection(
        current_targets=current,
        retention_candidates=band,
        previous_symbols=("510300.SH", "512170.SH"),
        top_k=2,
    )

    assert result.get_column("symbol").to_list() == ["510300.SH", "512170.SH"]
    assert result.get_column("weight").to_list() == [0.45, 0.45]


def test_rank_retention_does_not_override_explicit_cash_signal() -> None:
    factors = _trend_factors({
        "510300.SH": [-0.01, 0.03, 0.05, 0.9],
        "512880.SH": [0.03, 0.06, 0.09, 0.8],
    })
    common = {
        "candidates": ("510300.SH", "512880.SH"),
        "regime_symbol": "510300.SH",
        "cash_buffer": 0.1,
    }
    current = RegimeFilteredEtfTrendStrategy(top_k=1, **common).target_weights(
        AS_OF, factors
    )

    result = retain_ranked_target_selection(
        current_targets=current,
        retention_candidates=current,
        previous_symbols=("512880.SH",),
        top_k=1,
    )

    assert result.get_column("weight").to_list() == [0.0, 0.0]


def test_volatility_target_scales_exposure_without_changing_selection() -> None:
    dates = [dt.date(2026, 7, day) for day in (7, 8, 9, 10)]
    targets = pl.DataFrame({
        "as_of": [AS_OF, AS_OF],
        "strategy": ["s2", "s2"],
        "strategy_version": ["1.2.0", "1.2.0"],
        "symbol": ["510300.SH", "512880.SH"],
        "weight": [0.45, 0.45],
    })
    prices = pl.DataFrame([
        {
            "symbol": symbol,
            "trade_date": date,
            "adjusted_close": price,
            "adjustment_method": "TOTAL_RETURN_DIVIDEND",
            "source": "fixture",
        }
        for symbol in ("510300.SH", "512880.SH")
        for date, price in zip(dates, (100.0, 110.0, 99.0, 108.9), strict=True)
    ])
    half_realized_volatility = math.sqrt(0.0108) / 2

    result = scale_target_weights_to_volatility(
        targets=targets,
        prices=prices,
        lookback_observations=3,
        annualized_target_volatility=half_realized_volatility,
        annualization_sessions=1,
    )

    assert result.get_column("symbol").to_list() == ["510300.SH", "512880.SH"]
    assert result.get_column("weight").to_list() == pytest.approx([0.225, 0.225])


def test_volatility_target_does_not_leverage_low_risk_targets() -> None:
    dates = [dt.date(2026, 7, day) for day in (7, 8, 9, 10)]
    targets = pl.DataFrame({
        "as_of": [AS_OF],
        "strategy": ["s2"],
        "strategy_version": ["1.2.0"],
        "symbol": ["510300.SH"],
        "weight": [0.9],
    })
    prices = pl.DataFrame({
        "symbol": ["510300.SH"] * 4,
        "trade_date": dates,
        "adjusted_close": [100.0, 100.1, 100.2, 100.3],
        "adjustment_method": ["TOTAL_RETURN_DIVIDEND"] * 4,
        "source": ["fixture"] * 4,
    })

    result = scale_target_weights_to_volatility(
        targets=targets,
        prices=prices,
        lookback_observations=3,
        annualized_target_volatility=0.12,
        annualization_sessions=252,
    )

    assert result.get_column("weight").to_list() == [0.9]


def _trend_factors(values: dict[str, list[float]]) -> pl.DataFrame:
    names = ["momentum_20", "momentum_60", "momentum_120", "regression_slope_r2_60"]
    return pl.DataFrame([
        {
            "as_of": AS_OF,
            "symbol": symbol,
            "factor": name,
            "value": value,
            "factor_version": "trend_v1",
        }
        for symbol, symbol_values in values.items()
        for name, value in zip(names, symbol_values, strict=True)
    ])
