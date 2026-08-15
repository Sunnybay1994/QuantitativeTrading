from __future__ import annotations

import datetime as dt
import tomllib
from copy import deepcopy
from pathlib import Path

import polars as pl
import pytest

from quant.research.run_classic_factors import (
    _validate_config,
    select_frozen_liquid_universe,
    summarize_factors,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_frozen_universe_uses_only_ranked_pre_research_liquidity() -> None:
    rows: list[dict[str, object]] = []
    for symbol, amount in (("600001.SH", 30.0), ("600002.SH", 50.0), ("600003.SH", 40.0)):
        for offset in range(3):
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": dt.date(2019, 1, 1) + dt.timedelta(days=offset),
                    "amount": amount,
                }
            )
    universe = select_frozen_liquid_universe(
        pl.DataFrame(rows),
        top_n=2,
        minimum_observations=3,
        minimum_average_amount=35.0,
    )
    assert universe == ("600002.SH", "600003.SH")


def test_summary_applies_preregistered_thresholds_without_paper_status() -> None:
    rows: list[dict[str, object]] = []
    for factor, rank_ic, direction, returns in (
        ("pass", 0.02, 1, (0.03, 0.02)),
        ("reject", -0.01, -1, (-0.02, -0.03)),
    ):
        for fold in (1, 2, 3):
            for multiplier, total_return in zip((1.0, 2.0), returns, strict=True):
                rows.append(
                    {
                        "factor": factor,
                        "fold": fold,
                        "direction": direction,
                        "cost_multiplier": multiplier,
                        "test_rank_ic": rank_ic,
                        "total_return": total_return,
                    }
                )
    result = summarize_factors(
        pl.DataFrame(rows),
        factors=("pass", "reject"),
        admission={
            "minimum_mean_test_rank_ic": 0.01,
            "minimum_positive_test_folds": 2,
            "require_direction_consistency": True,
            "require_positive_2x_cost_return": True,
        },
    )
    assert result.select("factor", "research_status").rows() == [
        ("pass", "RESEARCH_ONLY"),
        ("reject", "REJECTED"),
    ]
    assert "PAPER_CANDIDATE" not in result.get_column("research_status").to_list()


def test_all_classic_factor_batch_configs_are_exactly_frozen() -> None:
    paths = (
        PROJECT_ROOT / "configs/research/m2_classic_daily_factors.toml",
        PROJECT_ROOT / "configs/research/m2_classic_daily_factors_second_batch.toml",
        PROJECT_ROOT / "configs/research/m2_classic_daily_factors_third_batch.toml",
    )
    configs = []
    for path in paths:
        with path.open("rb") as stream:
            config = tomllib.load(stream)
        _validate_config(config, threads=2)
        configs.append(config)

    changed = deepcopy(configs[1])
    changed["factors"]["maximum_median_absolute_rank_correlation"] = 0.81
    with pytest.raises(ValueError, match="invalid classic-factor config"):
        _validate_config(changed, threads=2)

    changed = deepcopy(configs[2])
    changed["factors"]["redundancy_reference_names"].reverse()
    with pytest.raises(ValueError, match="invalid classic-factor config"):
        _validate_config(changed, threads=2)
