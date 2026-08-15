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
    apply_redundancy_gate,
    build_daily_value_coverage,
    build_daily_value_panel,
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
