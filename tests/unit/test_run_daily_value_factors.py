from __future__ import annotations

import datetime as dt
import tomllib
from copy import deepcopy
from pathlib import Path
from typing import cast

import polars as pl
import pytest

from quant.factors import DAILY_VALUE_FACTOR_NAMES
from quant.research.run_daily_value_factors import (
    _validate_config,
    apply_coverage_gate,
    apply_expected_direction_gate,
    apply_redundancy_gate,
    build_daily_value_coverage,
    build_factor_coverage,
    build_daily_value_panel,
    build_monthly_liquidity_panel,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _bars() -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    start = dt.date(2025, 1, 1)
    for symbol_index, symbol in enumerate(("600001.SH", "000001.SZ")):
        for index in range(25):
            close = 10.0 + symbol_index + index / 10.0
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": start + dt.timedelta(days=index),
                    "open": close - 0.1,
                    "high": close + 0.2,
                    "low": close - 0.2,
                    "close": close,
                    "volume": 1_000.0 + index,
                    "amount": (1_000.0 + index) * close,
                    "adj_factor": 1.0,
                    "source": "fixture",
                }
            )
    return pl.DataFrame(rows)


def _daily_basic(*, loss_last: bool = False) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    start = dt.date(2025, 1, 1)
    for symbol_index, symbol in enumerate(("600001.SH", "000001.SZ")):
        for index in range(25):
            pe_ttm = 10.0 + symbol_index + index / 10.0
            if loss_last and symbol == "600001.SH" and index == 24:
                pe_ttm = -pe_ttm
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": start + dt.timedelta(days=index),
                    "close": 100.0 + index,
                    "turnover_rate": 1.0,
                    "turnover_rate_free": 1.2,
                    "volume_ratio": None,
                    "pe": pe_ttm,
                    "pe_ttm": pe_ttm,
                    "pb": 2.0 + symbol_index,
                    "ps": 5.0,
                    "ps_ttm": 4.0 + symbol_index,
                    "dividend_yield": 1.0,
                    "dividend_yield_ttm": 2.0 + symbol_index,
                    "total_shares": 10_000_000.0,
                    "float_shares": 8_000_000.0,
                    "free_float_shares": 7_000_000.0,
                    "total_market_value": 100_000_000.0 + symbol_index,
                    "circulating_market_value": 80_000_000.0,
                    "source": "tushare",
                }
            )
    return pl.DataFrame(rows)


def test_panel_binds_value_signals_to_bar_only_next_open_labels() -> None:
    bars = _bars()
    sessions = tuple(sorted(set(bars.get_column("trade_date").to_list())))
    first = build_daily_value_panel(
        daily_basic=_daily_basic(),
        bars=bars,
        sessions=sessions,
        horizons=(1, 5, 20),
    )
    changed_close = _daily_basic().with_columns(
        (pl.col("close") * 999.0).alias("close")
    )
    second = build_daily_value_panel(
        daily_basic=changed_close.reverse(),
        bars=bars.reverse(),
        sessions=sessions,
        horizons=(1, 5, 20),
    )
    compared = [
        *DAILY_VALUE_FACTOR_NAMES,
        "entry_open_1",
        "exit_open_1",
        "label_1",
        "entry_open_20",
        "exit_open_20",
        "label_20",
    ]
    assert first.select(compared).equals(second.select(compared), null_equal=True)
    assert cast(float, first.get_column("entry_open_1").drop_nulls().max()) < 20.0


def test_coverage_keeps_loss_null_separate_from_zero_dividend() -> None:
    bars = _bars()
    sessions = tuple(sorted(set(bars.get_column("trade_date").to_list())))
    panel = build_daily_value_panel(
        daily_basic=_daily_basic(loss_last=True),
        bars=bars,
        sessions=sessions,
        horizons=(1, 5, 20),
    )
    coverage = build_daily_value_coverage(panel)
    last = sessions[-1]
    ep = coverage.filter(
        (pl.col("factor") == "daily_ep_ttm_positive")
        & (pl.col("trade_date") == last)
    )
    dividend = coverage.filter(
        (pl.col("factor") == "daily_dividend_yield_ttm")
        & (pl.col("trade_date") == last)
    )
    assert ep.select("eligible_rows", "valid_rows").row(0) == (2, 1)
    assert dividend.select("eligible_rows", "valid_rows").row(0) == (2, 2)


def test_redundancy_gate_rejects_only_near_duplicate_passing_factor() -> None:
    summary = pl.DataFrame(
        {
            "factor": ["daily_bp_positive", "daily_ep_ttm_positive"],
            "research_status": ["RESEARCH_ONLY", "RESEARCH_ONLY"],
        }
    )
    redundancy = pl.DataFrame(
        {
            "factor_a": ["daily_bp_positive", "daily_ep_ttm_positive"],
            "factor_b": ["log_total_market_value", "alpha158_roc20"],
            "median_abs_rank_corr": [0.95, 0.20],
        }
    )
    result = apply_redundancy_gate(
        summary,
        redundancy_summary=redundancy,
        maximum_median_absolute_rank_correlation=0.80,
    )
    assert result.select("factor", "research_status").rows() == [
        ("daily_bp_positive", "REJECTED"),
        ("daily_ep_ttm_positive", "RESEARCH_ONLY"),
    ]


def test_redundancy_gate_is_symmetric_and_exact_threshold_rejects() -> None:
    summary = pl.DataFrame(
        {
            "factor": ["left", "right"],
            "research_status": ["RESEARCH_ONLY", "RESEARCH_ONLY"],
        }
    )
    redundancy = pl.DataFrame(
        {
            "factor_a": ["left"],
            "factor_b": ["right"],
            "median_abs_rank_corr": [0.80],
        }
    )
    result = apply_redundancy_gate(
        summary,
        redundancy_summary=redundancy,
        maximum_median_absolute_rank_correlation=0.80,
    )
    assert result.select("factor", "research_status").rows() == [
        ("left", "REJECTED"),
        ("right", "REJECTED"),
    ]


def test_monthly_coverage_and_direction_gates_fail_closed() -> None:
    summary = pl.DataFrame(
        {
            "factor": ["amihud", "turnover"],
            "research_status": ["RESEARCH_ONLY", "RESEARCH_ONLY"],
        }
    )
    dates = (dt.date(2024, 1, 31), dt.date(2024, 2, 29))
    coverage = pl.DataFrame(
        {
            "factor": ["amihud", "amihud", "turnover", "turnover"],
            "trade_date": [*dates, *dates],
            "eligible_rows": [125, 125, 125, 125],
            "valid_rows": [100, 100, 100, 99],
            "coverage": [0.80, 0.80, 0.80, 0.792],
        }
    )
    covered = apply_coverage_gate(
        summary,
        coverage=coverage,
        minimum_signal_symbols=100,
        minimum_median_coverage=0.80,
    )
    assert covered.select("factor", "coverage_passed", "research_status").rows() == [
        ("amihud", True, "RESEARCH_ONLY"),
        ("turnover", False, "REJECTED"),
    ]

    fold_metrics = pl.DataFrame(
        {
            "factor": ["amihud", "amihud", "turnover", "turnover"],
            "cost_multiplier": [1.0, 1.0, 1.0, 1.0],
            "direction": [1, 1, 1, 1],
        }
    )
    directed = apply_expected_direction_gate(
        summary,
        fold_metrics=fold_metrics,
        expected_directions={"amihud": 1, "turnover": -1},
    )
    assert directed.select(
        "factor", "expected_direction_passed", "research_status"
    ).rows() == [
        ("amihud", True, "RESEARCH_ONLY"),
        ("turnover", False, "REJECTED"),
    ]


def test_monthly_panel_uses_next_open_and_next_rebalance_dates() -> None:
    symbols = ("000001.SZ", "600001.SH")
    month_ordinals = tuple(range(1, 14))
    rows: list[dict[str, object]] = []
    daily_rows: list[dict[str, object]] = []
    sessions: list[dt.date] = []
    daily_template = _daily_basic().row(0, named=True)
    for month_index, ordinal in enumerate(month_ordinals):
        year = 2024 + (ordinal - 1) // 12
        month = (ordinal - 1) % 12 + 1
        for day in range(1, 17):
            trade_date = dt.date(year, month, day)
            sessions.append(trade_date)
            for symbol_index, symbol in enumerate(symbols):
                price = 10.0 + month_index + day / 100.0 + symbol_index
                rows.append(
                    {
                        "symbol": symbol,
                        "trade_date": trade_date,
                        "open": price,
                        "high": price + 0.1,
                        "low": price - 0.1,
                        "close": price,
                        "volume": 1_000.0,
                        "amount": 25_000_000.0,
                        "adj_factor": 1.0,
                        "source": "fixture",
                    }
                )
                daily_rows.append(
                    {
                        **daily_template,
                        "symbol": symbol,
                        "trade_date": trade_date,
                        "turnover_rate_free": float(month_index + 1),
                    }
                )
    unique_sessions = tuple(sorted(set(sessions)))
    signal_dates = tuple(
        dt.date(2024 + (ordinal - 1) // 12, (ordinal - 1) % 12 + 1, 16)
        for ordinal in month_ordinals
    )
    panel = build_monthly_liquidity_panel(
        daily_basic=pl.DataFrame(daily_rows),
        bars=pl.DataFrame(rows),
        sessions=unique_sessions,
        signal_dates=signal_dates,
        candidate_symbols=symbols,
    )
    first = panel.filter(
        (pl.col("symbol") == symbols[0]) & (pl.col("trade_date") == signal_dates[0])
    )
    assert first.select(
        "execution_date_rebalance", "exit_date_rebalance"
    ).row(0) == (dt.date(2024, 2, 1), dt.date(2024, 3, 1))
    assert build_factor_coverage(
        panel, factors=("amihud_illiquidity_monthly",)
    ).get_column("coverage").drop_nulls().min() == pytest.approx(1.0)


def test_daily_value_config_is_frozen_without_placeholder_snapshot() -> None:
    path = PROJECT_ROOT / "configs/research/m2_daily_value_factors.toml"
    with path.open("rb") as stream:
        config = tomllib.load(stream)
    _validate_config(config, threads=2)
    assert "daily_basic_snapshot_id" not in config["data"]

    changed = deepcopy(config)
    changed["factors"]["redundancy_reference_names"].reverse()
    with pytest.raises(ValueError, match="invalid daily-value-factor config"):
        _validate_config(changed, threads=2)

    with pytest.raises(ValueError, match="invalid daily-value-factor config"):
        _validate_config(config, threads=5)


@pytest.mark.parametrize(
    "name",
    ["m2_amihud_illiquidity.toml", "m2_free_float_turnover.toml"],
)
def test_monthly_liquidity_configs_are_frozen(name: str) -> None:
    path = PROJECT_ROOT / "configs/research" / name
    with path.open("rb") as stream:
        config = tomllib.load(stream)
    _validate_config(config, threads=2)

    wrong_coverage = deepcopy(config)
    wrong_coverage["factors"]["minimum_median_coverage"] = 0.799
    with pytest.raises(ValueError, match="invalid daily-value-factor config"):
        _validate_config(wrong_coverage, threads=2)

    with pytest.raises(ValueError, match="invalid daily-value-factor config"):
        _validate_config(config, threads=3)
