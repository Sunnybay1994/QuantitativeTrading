from __future__ import annotations

import datetime as dt
import tomllib
from copy import deepcopy
from pathlib import Path

import polars as pl
import pytest

from quant.factors import PIT_QUALITY_FACTOR_NAMES
from quant.research.classic_factor_evaluation import build_diagnostic_factor_targets
from quant.research.run_pit_quality_factors import (
    apply_pit_quality_coverage_gate,
    apply_redundancy_signal_coverage_gate,
    attach_redundancy_signal_coverage,
    _validate_config,
    build_pit_quality_coverage,
    build_pit_quality_panel,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _bars() -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    start = dt.date(2025, 1, 1)
    for symbol_index, symbol in enumerate(("600001.SH", "000001.SZ")):
        for index in range(50):
            close = 10.0 + symbol_index + index
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": start + dt.timedelta(days=index),
                    "open": close,
                    "high": close + 1.0,
                    "low": close - 1.0,
                    "close": close + 0.5,
                    "volume": 1_000.0 + index,
                    "amount": (1_000.0 + index) * close,
                    "adj_factor": 1.0,
                    "source": "fixture",
                }
            )
    return pl.DataFrame(rows)


def _daily_basic(signal_dates: tuple[dt.date, ...]) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for symbol_index, symbol in enumerate(("600001.SH", "000001.SZ")):
        for date in signal_dates:
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": date,
                    "close": 100.0,
                    "turnover_rate": 1.0,
                    "turnover_rate_free": 1.2,
                    "volume_ratio": None,
                    "pe": 10.0,
                    "pe_ttm": 10.0 + symbol_index,
                    "pb": 2.0 + symbol_index,
                    "ps": 5.0,
                    "ps_ttm": 4.0 + symbol_index,
                    "dividend_yield": 1.0,
                    "dividend_yield_ttm": 2.0,
                    "total_shares": 10_000_000.0,
                    "float_shares": 8_000_000.0,
                    "free_float_shares": 7_000_000.0,
                    "total_market_value": 100_000_000.0 + symbol_index,
                    "circulating_market_value": 80_000_000.0,
                    "source": "tushare",
                }
            )
    return pl.DataFrame(rows)


def _signals(signal_dates: tuple[dt.date, ...]) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for date_index, date in enumerate(signal_dates):
        for symbol_index, symbol in enumerate(("600001.SH", "000001.SZ")):
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": date,
                    "financial_period_end": dt.date(2024, 12, 31),
                    "pit_roe_ttm": 0.1 + symbol_index + date_index,
                    "pit_roa_ttm": 0.05 + symbol_index,
                    "pit_cash_profit_quality_ttm": (
                        None if date_index == 1 and symbol_index == 1 else 1.2
                    ),
                    "pit_total_accruals_ttm": -0.01 + symbol_index,
                }
            )
    return pl.DataFrame(rows)


def test_sparse_panel_uses_next_monthly_execution_as_portfolio_exit() -> None:
    bars = _bars()
    sessions = tuple(sorted(set(bars.get_column("trade_date").to_list())))
    signal_dates = (sessions[20], sessions[39])
    panel = build_pit_quality_panel(
        signal_values=_signals(signal_dates),
        daily_basic=_daily_basic(signal_dates),
        bars=bars,
        sessions=sessions,
    )

    first = panel.filter(pl.col("trade_date") == signal_dates[0])
    assert first.get_column("execution_date_rebalance").unique().to_list() == [sessions[21]]
    assert first.get_column("exit_date_rebalance").unique().to_list() == [sessions[40]]
    assert first.get_column("exit_date_20").unique().to_list() == [sessions[41]]

    targets, periods = build_diagnostic_factor_targets(
        panel,
        factor="pit_roe_ttm",
        direction=1,
        fold=1,
        test_start=signal_dates[0],
        test_end=sessions[40],
        top_k=1,
        rebalance_every_sessions=1,
        minimum_symbols=2,
        strategy_name="pit_quality",
        strategy_version="v1",
        return_column="label_rebalance",
        execution_date_column="execution_date_rebalance",
        exit_date_column="exit_date_rebalance",
    )
    assert targets.get_column("execution_date").unique().to_list() == [sessions[21]]
    assert periods.get_column("exit_date").to_list() == [sessions[40]]
    expected = (10.0 + 1 + 40) / (10.0 + 1 + 21) - 1.0
    assert periods.get_column("gross_return").item() == pytest.approx(expected)


def test_panel_is_row_order_invariant_and_daily_basic_close_is_not_label_authority() -> None:
    bars = _bars()
    sessions = tuple(sorted(set(bars.get_column("trade_date").to_list())))
    dates = (sessions[20], sessions[39])
    first = build_pit_quality_panel(
        signal_values=_signals(dates),
        daily_basic=_daily_basic(dates),
        bars=bars,
        sessions=sessions,
    )
    second = build_pit_quality_panel(
        signal_values=_signals(dates).reverse(),
        daily_basic=_daily_basic(dates)
        .with_columns((pl.col("close") * 999.0).alias("close"))
        .reverse(),
        bars=bars.reverse(),
        sessions=sessions,
    )
    compared = [
        *PIT_QUALITY_FACTOR_NAMES,
        "log_total_market_value",
        "entry_open_20",
        "exit_open_20",
        "label_20",
        "entry_open_rebalance",
        "exit_open_rebalance",
        "label_rebalance",
    ]
    assert first.select(compared).equals(second.select(compared), null_equal=True)


def test_coverage_preserves_factor_nulls_and_financial_period_range() -> None:
    date = dt.date(2025, 2, 28)
    eligibility = pl.DataFrame(
        {
            "as_of": [date] * 5,
            "symbol": [f"00000{index}.SZ" for index in range(1, 6)],
            "factor": ["pit_cash_profit_quality_ttm"] * 5,
            "financial_period_end": [dt.date(2024, 12, 31), None, None, None, None],
            "status": [
                "VALID",
                "MISSING_CHAIN",
                "NON_INDUSTRIAL",
                "INVALID_DENOMINATOR",
                "QUARANTINED",
            ],
        },
        schema={
            "as_of": pl.Date(),
            "symbol": pl.String(),
            "factor": pl.String(),
            "financial_period_end": pl.Date(),
            "status": pl.String(),
        },
    )
    coverage = build_pit_quality_coverage(eligibility)
    cash = coverage.filter(
        (pl.col("factor") == "pit_cash_profit_quality_ttm") & (pl.col("trade_date") == date)
    )
    assert cash.select(
        "eligible_rows",
        "valid_rows",
        "missing_chain_rows",
        "non_industrial_rows",
        "invalid_denominator_rows",
        "quarantined_rows",
        "coverage",
    ).row(0) == (
        5,
        1,
        1,
        1,
        1,
        1,
        0.2,
    )
    assert cash.get_column("min_period_end").item() == dt.date(2024, 12, 31)


def test_pit_quality_config_is_frozen_without_unpublished_snapshot_ids() -> None:
    path = PROJECT_ROOT / "configs/research/m2_pit_quality_factors.toml"
    with path.open("rb") as stream:
        config = tomllib.load(stream)
    with pytest.raises(ValueError, match="invalid PIT-quality-factor config"):
        _validate_config(config, threads=2)
    assert "financial_snapshot_id" not in config["data"]
    assert "daily_basic_snapshot_id" not in config["data"]
    assert config["portfolio"]["rebalance_every_signals"] == 1
    assert config["factors"]["report_type_freeze_status"] == "UNFROZEN"
    assert config["factors"]["allowed_report_types"] == []

    frozen = deepcopy(config)
    frozen["factors"]["report_type_freeze_status"] = "FROZEN"
    frozen["factors"]["allowed_report_types"] = ["1"]
    _validate_config(frozen, threads=2)

    changed = deepcopy(frozen)
    changed["factors"]["redundancy_reference_names"].reverse()
    with pytest.raises(ValueError, match="invalid PIT-quality-factor config"):
        _validate_config(changed, threads=2)

    with pytest.raises(ValueError, match="invalid PIT-quality-factor config"):
        _validate_config(frozen, threads=3)


def test_redundancy_calendar_coverage_fails_closed_for_one_missing_month() -> None:
    redundancy = pl.DataFrame(
        {
            "factor_a": ["pit_roe_ttm", "pit_roe_ttm"],
            "factor_b": ["control_a", "control_b"],
            "dates": [12, 11],
            "median_rank_corr": [0.1, 0.2],
            "median_abs_rank_corr": [0.1, 0.2],
        }
    )
    covered = attach_redundancy_signal_coverage(
        redundancy,
        expected_signal_dates=12,
        minimum_coverage=1.0,
    )
    assert covered.get_column("signal_date_coverage_passed").to_list() == [
        True,
        False,
    ]
    factor_summary = pl.DataFrame(
        {
            "factor": ["pit_roe_ttm"],
            "research_status": ["RESEARCH_ONLY"],
        }
    )
    gated = apply_redundancy_signal_coverage_gate(
        factor_summary,
        redundancy_summary=covered,
    )
    assert gated.get_column("research_status").item() == "REJECTED"


def _coverage_rows(
    dates: tuple[dt.date, ...], *, valid_rows: int, eligible_rows: int
) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "factor": ["pit_roe_ttm"] * len(dates),
            "trade_date": list(dates),
            "eligible_rows": [eligible_rows] * len(dates),
            "valid_rows": [valid_rows] * len(dates),
            "missing_chain_rows": [eligible_rows - valid_rows] * len(dates),
            "non_industrial_rows": [0] * len(dates),
            "invalid_denominator_rows": [0] * len(dates),
            "quarantined_rows": [0] * len(dates),
            "coverage": [valid_rows / eligible_rows] * len(dates),
            "min_period_end": [dt.date(2024, 12, 31)] * len(dates),
            "max_period_end": [dt.date(2024, 12, 31)] * len(dates),
        }
    )


def test_signal_coverage_gate_accepts_exactly_eighty_percent() -> None:
    dates = tuple(dt.date(2025, month, 28) for month in range(1, 6))
    summary = pl.DataFrame(
        {"factor": ["pit_roe_ttm"], "research_status": ["RESEARCH_ONLY"]}
    )
    gated, completed = apply_pit_quality_coverage_gate(
        summary,
        coverage=_coverage_rows(dates, valid_rows=100, eligible_rows=125),
        signal_dates=dates,
        minimum_signal_symbols=100,
        minimum_median_signal_coverage=0.80,
    )
    assert gated.select(
        "median_signal_coverage", "pit_signal_coverage_passed", "research_status"
    ).row(0) == (0.8, True, "RESEARCH_ONLY")
    assert completed.get_column("daily_minimum_signal_symbols_passed").all()


def test_signal_coverage_gate_rejects_799_percent_and_missing_schedule_date() -> None:
    dates = tuple(dt.date(2025, month, 28) for month in range(1, 6))
    summary = pl.DataFrame(
        {"factor": ["pit_roe_ttm"], "research_status": ["RESEARCH_ONLY"]}
    )
    low, _ = apply_pit_quality_coverage_gate(
        summary,
        coverage=_coverage_rows(dates, valid_rows=799, eligible_rows=1000),
        signal_dates=dates,
        minimum_signal_symbols=100,
        minimum_median_signal_coverage=0.80,
    )
    assert low.get_column("research_status").item() == "REJECTED"

    missing, completed = apply_pit_quality_coverage_gate(
        summary,
        coverage=_coverage_rows(dates[:-1], valid_rows=800, eligible_rows=1000),
        signal_dates=dates,
        minimum_signal_symbols=100,
        minimum_median_signal_coverage=0.80,
    )
    assert missing.get_column("research_status").item() == "REJECTED"
    absent = completed.filter(pl.col("trade_date") == dates[-1])
    assert absent.select("valid_rows", "coverage").row(0) == (0, 0.0)


def test_signal_coverage_gate_rejects_shifted_schedule_date() -> None:
    dates = (dt.date(2025, 1, 31), dt.date(2025, 2, 28))
    shifted = (dates[0], dt.date(2025, 3, 3))
    summary = pl.DataFrame(
        {"factor": ["pit_roe_ttm"], "research_status": ["RESEARCH_ONLY"]}
    )
    with pytest.raises(ValueError, match="outside the pre-registered calendar"):
        apply_pit_quality_coverage_gate(
            summary,
            coverage=_coverage_rows(shifted, valid_rows=100, eligible_rows=100),
            signal_dates=dates,
            minimum_signal_symbols=100,
            minimum_median_signal_coverage=0.80,
        )
