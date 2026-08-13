import datetime as dt

import polars as pl

from quant.research.run_s1_walk_forward import (
    _CODE_PATHS,
    _monthly_signal_dates,
    _research_spec,
    _volatility_target_spec,
    make_folds,
    metrics,
)


def test_research_code_digest_covers_every_factor_implementation() -> None:
    assert "src/quant/factors/trend.py" in _CODE_PATHS
    assert "src/quant/factors/risk.py" in _CODE_PATHS


def test_walk_forward_builds_only_complete_folds() -> None:
    folds = make_folds(
        start=dt.date(2023, 1, 1),
        end=dt.date(2026, 7, 10),
        train_months=24,
        validation_months=6,
        test_months=6,
        step_months=6,
    )
    assert len(folds) == 2
    assert folds[0].validation_start == dt.date(2025, 1, 1)
    assert folds[0].test_end == dt.date(2025, 12, 31)
    assert folds[1].train_start == dt.date(2023, 7, 1)
    assert folds[1].test_end == dt.date(2026, 6, 30)


def test_metrics_include_unresolved_target_gap_diagnostics() -> None:
    dates = [dt.date(2026, 1, 5), dt.date(2026, 1, 6)]
    nav = pl.DataFrame({
        "strategy": ["s2", "s2"],
        "date": dates,
        "equity": [10000.0, 10100.0],
        "unit_nav": [1.0, 1.01],
        "cash": [100.0, 100.0],
        "market_value": [9900.0, 10000.0],
        "cumulative_fees": [5.0, 5.0],
    })
    trades = pl.DataFrame({
        "strategy": ["s2"],
        "date": [dates[0]],
        "symbol": ["510300.SH"],
        "side": ["BUY"],
        "quantity": [900],
        "price": [11.0],
        "notional": [9900.0],
        "fee": [5.0],
        "slippage_cost": [0.0],
    })
    target_gaps = pl.DataFrame({
        "gap_reason": ["CASH_CONSTRAINT", "NONE"],
        "absolute_notional_gap": [100.0, 0.0],
    })

    result = metrics(
        nav,
        trades,
        initial_cash=10000.0,
        target_gaps=target_gaps,
    )

    assert result["target_gap_count"] == 1.0
    assert result["absolute_target_gap_notional"] == 100.0


def test_signal_dates_support_bimonthly_single_variable_comparison() -> None:
    prices = pl.DataFrame({
        "trade_date": [
            dt.date(2025, 12, 31),
            dt.date(2026, 1, 30),
            dt.date(2026, 2, 27),
            dt.date(2026, 3, 31),
            dt.date(2026, 4, 30),
        ]
    })

    result = _monthly_signal_dates(
        prices,
        start=dt.date(2026, 1, 1),
        end=dt.date(2026, 4, 30),
        every_months=2,
    )

    assert result == [
        dt.date(2025, 12, 31),
        dt.date(2026, 1, 30),
        dt.date(2026, 3, 31),
    ]


def test_failed_hypothesis_can_be_recorded_as_rejected() -> None:
    spec = _research_spec({
        "research": {
            "hypothesis_id": "s2-bimonthly-regime-filter-v1",
            "hypothesis": "A frozen hypothesis that failed its acceptance criterion.",
            "strategy_kind": "etf_regime_trend",
            "strategy_version": "1.1.0",
            "conclusion": "REJECTED",
            "random_seed": 0,
        }
    })

    assert spec.conclusion == "REJECTED"


def test_market_breadth_strategy_kind_is_an_explicit_research_contract() -> None:
    spec = _research_spec({
        "research": {
            "hypothesis_id": "s2-fixed-majority-market-breadth-v1",
            "hypothesis": "A strict-majority breadth hypothesis.",
            "strategy_kind": "etf_breadth_regime_trend",
            "strategy_version": "1.4.0",
            "conclusion": "REJECTED",
            "random_seed": 0,
        }
    })

    assert spec.strategy_kind == "etf_breadth_regime_trend"
    assert spec.conclusion == "REJECTED"


def test_low_volatility_strategy_kind_is_an_explicit_research_contract() -> None:
    spec = _research_spec({
        "research": {
            "hypothesis_id": "s2-fixed-low-volatility-selection-v1",
            "hypothesis": "A fixed low-volatility selection hypothesis.",
            "strategy_kind": "etf_regime_low_volatility",
            "strategy_version": "1.0.0",
            "conclusion": "RESEARCH_ONLY",
            "random_seed": 0,
        }
    })

    assert spec.strategy_kind == "etf_regime_low_volatility"


def test_risk_adjusted_momentum_kind_is_an_explicit_research_contract() -> None:
    spec = _research_spec({
        "research": {
            "hypothesis_id": "s2-fixed-risk-adjusted-momentum-v1",
            "hypothesis": "A fixed momentum-per-unit-risk ranking hypothesis.",
            "strategy_kind": "etf_regime_risk_adjusted_momentum",
            "strategy_version": "1.0.0",
            "conclusion": "RESEARCH_ONLY",
            "random_seed": 0,
        }
    })

    assert spec.strategy_kind == "etf_regime_risk_adjusted_momentum"


def test_volatility_target_config_is_explicit_and_unlevered() -> None:
    assert _volatility_target_spec({
        "volatility_target": {
            "lookback_observations": 60,
            "annualized_volatility": 0.12,
            "annualization_sessions": 252,
        }
    }) == (60, 0.12, 252)
