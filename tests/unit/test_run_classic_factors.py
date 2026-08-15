from __future__ import annotations

import datetime as dt
import tomllib
from copy import deepcopy
from pathlib import Path

import polars as pl
import pytest

from quant.research.lightweight_run import ResearchFoldV1
from quant.research.run_classic_factors import (
    _validate_config,
    apply_fifth_batch_admission_gates,
    apply_fourth_batch_admission_gates,
    apply_market_risk_admission_gates,
    evaluate_factor_coverage,
    evaluate_rebalance_schedule_alignment,
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
        PROJECT_ROOT / "configs/research/m2_classic_downside_beta_510300.toml",
        PROJECT_ROOT / "configs/research/m2_classic_daily_factors_fourth_batch.toml",
        PROJECT_ROOT / "configs/research/m2_classic_daily_factors_fifth_batch.toml",
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

    for section, key, value in (
        ("market_risk", "benchmark", "000300.SH"),
        ("market_risk", "expected_direction", 1),
        ("coverage", "minimum_rebalance_symbols", 99),
    ):
        changed = deepcopy(configs[3])
        changed[section][key] = value
        with pytest.raises(ValueError, match="invalid classic-factor config"):
            _validate_config(changed, threads=2)

    for section, key, value in (
        ("factors", "maximum_median_absolute_rank_correlation", 0.81),
        ("coverage", "minimum_rebalance_symbols", 99),
    ):
        changed = deepcopy(configs[4])
        changed[section][key] = value
        with pytest.raises(ValueError, match="invalid classic-factor config"):
            _validate_config(changed, threads=2)

    changed = deepcopy(configs[4])
    changed["factors"]["redundancy_reference_names"].reverse()
    with pytest.raises(ValueError, match="invalid classic-factor config"):
        _validate_config(changed, threads=2)

    for section, key, value in (
        ("factors", "maximum_median_absolute_rank_correlation", 0.81),
        ("max_lottery", "window_sessions", 21),
        ("max_lottery", "expected_direction", 1),
        ("max_lottery", "trial_budget", 2),
        ("coverage", "minimum_rebalance_symbols", 99),
    ):
        changed = deepcopy(configs[5])
        changed[section][key] = value
        with pytest.raises(ValueError, match="invalid classic-factor config"):
            _validate_config(changed, threads=2)

    changed = deepcopy(configs[5])
    changed["factors"]["redundancy_reference_names"].reverse()
    with pytest.raises(ValueError, match="invalid classic-factor config"):
        _validate_config(changed, threads=2)


def test_factor_coverage_and_rebalance_schedule_are_fail_closed() -> None:
    trade_date = dt.date(2025, 1, 6)
    rows = [
        {
            "symbol": f"{index:06d}.SH",
            "trade_date": trade_date,
            "exit_date_20": trade_date,
            "downside_beta": float(index) if index < 80 else None,
        }
        for index in range(100)
    ]
    panel = pl.DataFrame(rows)
    fold = ResearchFoldV1(
        fold=1,
        train_start=dt.date(2024, 1, 1),
        train_end=dt.date(2024, 6, 30),
        validation_start=dt.date(2024, 7, 1),
        validation_end=dt.date(2024, 12, 31),
        test_start=trade_date,
        test_end=trade_date,
    )
    daily, summary = evaluate_factor_coverage(
        panel,
        factors=("downside_beta",),
        start_date=trade_date,
        end_date=trade_date,
        folds=(fold,),
        rebalance_every_sessions=20,
        minimum_rebalance_symbols=80,
        minimum_median_coverage=0.80,
    )
    assert daily.select("valid_rows", "coverage", "scheduled_rebalance").row(0) == (
        80,
        0.8,
        True,
    )
    assert summary.get_column("coverage_passed").item() is True

    changed = panel.with_columns(
        pl.when(pl.col("symbol") == "000079.SH")
        .then(None)
        .otherwise(pl.col("downside_beta"))
        .alias("downside_beta")
    )
    _, failed = evaluate_factor_coverage(
        changed,
        factors=("downside_beta",),
        start_date=trade_date,
        end_date=trade_date,
        folds=(fold,),
        rebalance_every_sessions=20,
        minimum_rebalance_symbols=80,
        minimum_median_coverage=0.80,
    )
    assert failed.get_column("coverage_passed").item() is False

    targets = pl.DataFrame(
        {"factor": ["downside_beta"], "fold": [1], "as_of": [trade_date]}
    )
    aligned = evaluate_rebalance_schedule_alignment(
        panel,
        targets,
        factors=("downside_beta",),
        folds=(fold,),
        rebalance_every_sessions=20,
    )
    assert aligned.get_column("schedule_aligned").item() is True
    shifted = targets.with_columns(
        pl.lit(trade_date + dt.timedelta(days=1)).alias("as_of")
    )
    misaligned = evaluate_rebalance_schedule_alignment(
        panel,
        shifted,
        factors=("downside_beta",),
        folds=(fold,),
        rebalance_every_sessions=20,
    )
    assert misaligned.select(
        "missing_rebalance_dates", "unexpected_rebalance_dates", "schedule_aligned"
    ).row(0) == (1, 1, False)
    assert misaligned.get_column("missing_dates").to_list() == [[trade_date]]
    assert misaligned.get_column("unexpected_dates").to_list() == [
        [trade_date + dt.timedelta(days=1)]
    ]


def test_market_risk_gates_enforce_direction_redundancy_coverage_and_schedule() -> None:
    summary = pl.DataFrame(
        {
            "factor": ["downside_beta"],
            "mean_test_rank_ic": [0.02],
            "positive_test_folds": [3],
            "direction_consistent": [True],
            "one_x_chained_return": [0.03],
            "two_x_chained_return": [0.01],
            "research_status": ["RESEARCH_ONLY"],
        }
    )
    folds = pl.DataFrame(
        {
            "factor": ["downside_beta"] * 3,
            "cost_multiplier": [1.0] * 3,
            "direction": [-1] * 3,
        }
    )
    redundancy = pl.DataFrame(
        {
            "factor_a": ["downside_beta"],
            "factor_b": ["control"],
            "median_abs_rank_corr": [0.79],
        }
    )
    coverage = pl.DataFrame(
        {
            "factor": ["downside_beta"],
            "dates": [100],
            "scheduled_rebalance_dates": [10],
            "minimum_rebalance_valid_rows": [100],
            "median_coverage": [0.80],
            "coverage_passed": [True],
        }
    )
    schedule = pl.DataFrame(
        {
            "factor": ["downside_beta"],
            "fold": [1],
            "schedule_aligned": [True],
        }
    )

    def apply(
        *,
        fold_metrics: pl.DataFrame = folds,
        redundancy_summary: pl.DataFrame = redundancy,
        coverage_summary: pl.DataFrame = coverage,
        schedule_alignment: pl.DataFrame = schedule,
    ) -> pl.DataFrame:
        return apply_market_risk_admission_gates(
            summary,
            fold_metrics=fold_metrics,
            redundancy_summary=redundancy_summary,
            coverage_summary=coverage_summary,
            schedule_alignment=schedule_alignment,
            expected_direction=-1,
            maximum_median_absolute_rank_correlation=0.80,
        )

    assert apply().get_column("research_status").item() == "RESEARCH_ONLY"
    assert (
        apply(
            redundancy_summary=redundancy.with_columns(
                pl.lit(0.80).alias("median_abs_rank_corr")
            )
        )
        .get_column("research_status")
        .item()
        == "REJECTED"
    )
    assert (
        apply(
            fold_metrics=folds.with_columns(pl.lit(1).alias("direction"))
        ).get_column("research_status").item()
        == "REJECTED"
    )
    assert (
        apply(
            coverage_summary=coverage.with_columns(
                pl.lit(False).alias("coverage_passed")
            )
        )
        .get_column("research_status")
        .item()
        == "REJECTED"
    )
    assert (
        apply(
            schedule_alignment=schedule.with_columns(
                pl.lit(False).alias("schedule_aligned")
            )
        )
        .get_column("research_status")
        .item()
        == "REJECTED"
    )


def test_fourth_batch_gates_enforce_redundancy_coverage_and_schedule() -> None:
    summary = pl.DataFrame(
        {
            "factor": ["alpha158_resi20"],
            "mean_test_rank_ic": [0.02],
            "positive_test_folds": [3],
            "direction_consistent": [True],
            "one_x_chained_return": [0.03],
            "two_x_chained_return": [0.01],
            "research_status": ["RESEARCH_ONLY"],
            "max_median_abs_rank_corr": [0.79],
            "combination_eligible": [True],
        }
    )
    redundancy = pl.DataFrame(
        {
            "factor_a": ["alpha158_resi20"],
            "factor_b": ["alpha158_beta20"],
            "median_abs_rank_corr": [0.79],
        }
    )
    coverage = pl.DataFrame(
        {
            "factor": ["alpha158_resi20"],
            "dates": [100],
            "scheduled_rebalance_dates": [10],
            "minimum_rebalance_valid_rows": [100],
            "median_coverage": [0.80],
            "coverage_passed": [True],
        }
    )
    schedule = pl.DataFrame(
        {
            "factor": ["alpha158_resi20"],
            "fold": [1],
            "schedule_aligned": [True],
        }
    )

    def apply(
        *,
        redundancy_summary: pl.DataFrame = redundancy,
        coverage_summary: pl.DataFrame = coverage,
        schedule_alignment: pl.DataFrame = schedule,
    ) -> pl.DataFrame:
        return apply_fourth_batch_admission_gates(
            summary,
            redundancy_summary=redundancy_summary,
            coverage_summary=coverage_summary,
            schedule_alignment=schedule_alignment,
            maximum_median_absolute_rank_correlation=0.80,
        )

    assert apply().get_column("research_status").item() == "RESEARCH_ONLY"
    assert (
        apply(
            redundancy_summary=redundancy.with_columns(
                pl.lit(0.80).alias("median_abs_rank_corr")
            )
        )
        .get_column("research_status")
        .item()
        == "REJECTED"
    )
    assert (
        apply(
            coverage_summary=coverage.with_columns(
                pl.lit(False).alias("coverage_passed")
            )
        )
        .get_column("research_status")
        .item()
        == "REJECTED"
    )
    assert (
        apply(
            schedule_alignment=schedule.with_columns(
                pl.lit(False).alias("schedule_aligned")
            )
        )
        .get_column("research_status")
        .item()
        == "REJECTED"
    )


def test_fifth_batch_gates_enforce_fixed_direction_and_all_fail_closed_edges() -> None:
    factor = "max_daily_return_20"
    summary = pl.DataFrame(
        {
            "factor": [factor],
            "mean_test_rank_ic": [0.02],
            "positive_test_folds": [3],
            "direction_consistent": [True],
            "one_x_chained_return": [0.03],
            "two_x_chained_return": [0.01],
            "research_status": ["RESEARCH_ONLY"],
            "max_median_abs_rank_corr": [0.79],
            "combination_eligible": [True],
        }
    )
    folds = pl.DataFrame(
        {
            "factor": [factor] * 3,
            "fold": [1, 2, 3],
            "cost_multiplier": [1.0] * 3,
            "direction": [-1] * 3,
            "validation_observed_direction": [-1] * 3,
        }
    )
    redundancy = pl.DataFrame(
        {
            "factor_a": [factor],
            "factor_b": ["alpha158_std20"],
            "median_abs_rank_corr": [0.79],
        }
    )
    coverage = pl.DataFrame(
        {
            "factor": [factor],
            "dates": [100],
            "scheduled_rebalance_dates": [10],
            "minimum_rebalance_valid_rows": [100],
            "median_coverage": [0.80],
            "coverage_passed": [True],
        }
    )
    schedule = pl.DataFrame(
        {
            "factor": [factor],
            "fold": [1],
            "schedule_aligned": [True],
        }
    )

    def apply(
        *,
        fold_metrics: pl.DataFrame = folds,
        redundancy_summary: pl.DataFrame = redundancy,
        coverage_summary: pl.DataFrame = coverage,
        schedule_alignment: pl.DataFrame = schedule,
    ) -> pl.DataFrame:
        return apply_fifth_batch_admission_gates(
            summary,
            fold_metrics=fold_metrics,
            redundancy_summary=redundancy_summary,
            coverage_summary=coverage_summary,
            schedule_alignment=schedule_alignment,
            expected_direction=-1,
            maximum_median_absolute_rank_correlation=0.80,
        )

    assert apply().get_column("research_status").item() == "RESEARCH_ONLY"
    assert (
        apply(
            fold_metrics=folds.with_columns(
                pl.when(pl.col("fold") == 2)
                .then(1)
                .otherwise(pl.col("validation_observed_direction"))
                .alias("validation_observed_direction")
            )
        ).get_column("research_status").item()
        == "REJECTED"
    )
    assert (
        apply(
            fold_metrics=folds.with_columns(pl.lit(1).alias("direction"))
        ).get_column("research_status").item()
        == "REJECTED"
    )
    assert (
        apply(
            redundancy_summary=redundancy.with_columns(
                pl.lit(0.80).alias("median_abs_rank_corr")
            )
        ).get_column("research_status").item()
        == "REJECTED"
    )
    assert (
        apply(
            coverage_summary=coverage.with_columns(
                pl.lit(False).alias("coverage_passed")
            )
        ).get_column("research_status").item()
        == "REJECTED"
    )
    assert (
        apply(
            schedule_alignment=schedule.with_columns(
                pl.lit(False).alias("schedule_aligned")
            )
        ).get_column("research_status").item()
        == "REJECTED"
    )
