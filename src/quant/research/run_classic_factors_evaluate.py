"""Walk-forward evaluation and coverage for classic factor research."""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, cast

import polars as pl

from quant.research.lightweight_run import ResearchFoldV1
from quant.research.m3.contracts import AShareCostPeriod
from quant.research.classic_factor_evaluation import (
    build_diagnostic_factor_targets,
    evaluate_factor_period,
    simulate_diagnostic_factor_portfolio,
)


def _aggregate_redundancy_by_factor(
    summary: pl.DataFrame,
    redundancy_summary: pl.DataFrame,
) -> pl.DataFrame:
    """Aggregate validated redundancy incidents for every summary candidate."""
    required_summary_columns = {"factor", "research_status"}
    required_redundancy_columns = {
        "factor_a",
        "factor_b",
        "median_abs_rank_corr",
    }
    if (
        not isinstance(summary, pl.DataFrame)
        or summary.is_empty()
        or not required_summary_columns.issubset(summary.columns)
        or not isinstance(redundancy_summary, pl.DataFrame)
        or redundancy_summary.is_empty()
        or not required_redundancy_columns.issubset(redundancy_summary.columns)
    ):
        raise ValueError("invalid classic redundancy aggregation request")

    for column in ("factor", "research_status"):
        if summary.schema[column] != pl.String:
            raise ValueError("classic summary string contract is invalid")
        values = summary.get_column(column).to_list()
        if any(type(value) is not str or not value for value in values):
            raise ValueError("classic summary string contract is invalid")
    statuses = cast(list[str], summary.get_column("research_status").to_list())
    if not set(statuses) <= {"RESEARCH_ONLY", "REJECTED"}:
        raise ValueError("classic summary status contract is invalid")
    for column in ("factor_a", "factor_b"):
        if redundancy_summary.schema[column] != pl.String:
            raise ValueError("classic redundancy endpoint contract is invalid")
        values = redundancy_summary.get_column(column).to_list()
        if any(type(value) is not str or not value for value in values):
            raise ValueError("classic redundancy endpoint contract is invalid")

    summary_factors = cast(list[str], summary.get_column("factor").to_list())
    if len(summary_factors) != len(set(summary_factors)):
        raise ValueError("classic summary factors are not unique")
    candidate_set = set(summary_factors)
    seen_pairs: set[tuple[str, str]] = set()
    maximum_by_factor: dict[str, int | float | Decimal] = {}
    for row in redundancy_summary.iter_rows(named=True):
        factor_a = cast(str, row["factor_a"])
        factor_b = cast(str, row["factor_b"])
        if factor_a == factor_b:
            raise ValueError("classic redundancy pair endpoints are not distinct")
        correlation = row["median_abs_rank_corr"]
        if isinstance(correlation, bool):
            raise ValueError("classic redundancy correlation contract is invalid")
        if not isinstance(correlation, (int, float, Decimal)):
            raise ValueError("classic redundancy correlation contract is invalid")
        numeric_correlation = cast(int | float | Decimal, correlation)
        try:
            finite = math.isfinite(float(numeric_correlation))
        except (OverflowError, TypeError, ValueError):
            finite = False
        if not finite:
            raise ValueError("classic redundancy correlation contract is invalid")
        if numeric_correlation < 0 or numeric_correlation > 1:
            raise ValueError("classic redundancy correlation must be between 0 and 1")

        pair: tuple[str, str] = (
            min(factor_a, factor_b),
            max(factor_a, factor_b),
        )
        if pair in seen_pairs:
            raise ValueError("classic redundancy pairs are not unique")
        seen_pairs.add(pair)
        for factor in (factor_a, factor_b):
            if factor in candidate_set:
                previous = maximum_by_factor.get(factor)
                if previous is None or float(numeric_correlation) > float(previous):
                    maximum_by_factor[factor] = numeric_correlation

    return pl.DataFrame(
        {
            "factor": summary_factors,
            "max_median_abs_rank_corr": [
                maximum_by_factor.get(factor) for factor in summary_factors
            ],
        },
        schema={
            "factor": pl.String,
            "max_median_abs_rank_corr": redundancy_summary.schema[
                "median_abs_rank_corr"
            ],
        },
    )


def select_frozen_liquid_universe(
    bars: pl.DataFrame,
    *,
    top_n: int,
    minimum_observations: int,
    minimum_average_amount: float,
) -> tuple[str, ...]:
    """Freeze a universe using only data available in the pre-research window."""
    if (
        type(top_n) is not int
        or top_n <= 0
        or type(minimum_observations) is not int
        or minimum_observations <= 0
        or not math.isfinite(minimum_average_amount)
        or minimum_average_amount <= 0
    ):
        raise ValueError("invalid frozen-universe request")
    ranked = (
        bars.group_by("symbol")
        .agg(
            pl.len().alias("observations"),
            pl.col("amount").mean().alias("average_amount"),
        )
        .filter(
            (pl.col("observations") >= minimum_observations)
            & (pl.col("average_amount") >= minimum_average_amount)
        )
        .sort("average_amount", "symbol", descending=[True, False])
        .head(top_n)
    )
    if ranked.height != top_n:
        raise ValueError("not enough securities for frozen universe")
    return tuple(sorted(ranked.get_column("symbol").to_list()))


def evaluate_walk_forward(
    *,
    panel: pl.DataFrame,
    factors: tuple[str, ...],
    horizons: tuple[int, ...],
    folds: tuple[ResearchFoldV1, ...],
    minimum_symbols: int,
    groups: int,
    top_k: int,
    rebalance_every: int,
    initial_cash: Decimal,
    cost_multipliers: tuple[Decimal, ...],
    costs: tuple[AShareCostPeriod, ...],
    strategy_name: str,
    strategy_version: str,
    portfolio_return_column: str = "label_20",
    portfolio_execution_date_column: str = "execution_date_20",
    portfolio_exit_date_column: str = "exit_date_20",
    portfolio_annualization_periods: float = 252.0 / 20.0,
    ic_newey_west_lag: int | None = None,
    fixed_direction: int | None = None,
) -> dict[str, pl.DataFrame]:
    """Evaluate untouched tests after validation or a pre-registered direction."""
    if fixed_direction is not None and (
        type(fixed_direction) is not int or fixed_direction not in {-1, 1}
    ):
        raise ValueError("invalid fixed factor direction")
    daily_frames: list[pl.DataFrame] = []
    group_frames: list[pl.DataFrame] = []
    metric_rows: list[dict[str, object]] = []
    target_frames: list[pl.DataFrame] = []
    nav_frames: list[pl.DataFrame] = []
    for fold in folds:
        for factor in factors:
            raw_validation_daily, raw_validation_groups, raw_validation_metrics = (
                evaluate_factor_period(
                    panel,
                    factor=factor,
                    horizon=20,
                    start_date=fold.validation_start,
                    end_date=fold.validation_end,
                    minimum_symbols=minimum_symbols,
                    groups=groups,
                    newey_west_lag=ic_newey_west_lag,
                )
            )
            validation_observed_direction = (
                1 if raw_validation_metrics["rank_ic_mean"] >= 0 else -1
            )
            direction = (
                validation_observed_direction
                if fixed_direction is None
                else fixed_direction
            )
            if direction == 1:
                validation_daily = raw_validation_daily
                validation_groups = raw_validation_groups
                validation_metrics = raw_validation_metrics
            else:
                validation_daily, validation_groups, validation_metrics = (
                    evaluate_factor_period(
                        panel,
                        factor=factor,
                        horizon=20,
                        start_date=fold.validation_start,
                        end_date=fold.validation_end,
                        minimum_symbols=minimum_symbols,
                        groups=groups,
                        direction=direction,
                        newey_west_lag=ic_newey_west_lag,
                    )
                )
            daily_frames.append(
                _with_evaluation_identity(
                    validation_daily,
                    fold=fold.fold,
                    period="validation",
                    factor=factor,
                    horizon=20,
                    direction=direction,
                )
            )
            group_frames.append(
                _with_evaluation_identity(
                    validation_groups,
                    fold=fold.fold,
                    period="validation",
                    factor=factor,
                    horizon=20,
                    direction=direction,
                )
            )
            test20_metrics: dict[str, float | int] | None = None
            for horizon in horizons:
                test_daily, test_groups, test_metrics = evaluate_factor_period(
                    panel,
                    factor=factor,
                    horizon=horizon,
                    start_date=fold.test_start,
                    end_date=fold.test_end,
                    minimum_symbols=minimum_symbols,
                    groups=groups,
                    direction=direction,
                    newey_west_lag=ic_newey_west_lag,
                )
                daily_frames.append(
                    _with_evaluation_identity(
                        test_daily,
                        fold=fold.fold,
                        period="test",
                        factor=factor,
                        horizon=horizon,
                        direction=direction,
                    )
                )
                group_frames.append(
                    _with_evaluation_identity(
                        test_groups,
                        fold=fold.fold,
                        period="test",
                        factor=factor,
                        horizon=horizon,
                        direction=direction,
                    )
                )
                if horizon == 20:
                    test20_metrics = test_metrics
            if test20_metrics is None:
                raise ValueError("test horizon 20 is missing")
            targets, periods = build_diagnostic_factor_targets(
                panel,
                factor=factor,
                direction=direction,
                fold=fold.fold,
                test_start=fold.test_start,
                test_end=fold.test_end,
                top_k=top_k,
                rebalance_every_sessions=rebalance_every,
                minimum_symbols=minimum_symbols,
                strategy_name=strategy_name,
                strategy_version=strategy_version,
                return_column=portfolio_return_column,
                execution_date_column=portfolio_execution_date_column,
                exit_date_column=portfolio_exit_date_column,
            )
            target_frames.append(targets)
            holding_outcomes = panel.select(
                pl.col("trade_date").alias("as_of"),
                "symbol",
                pl.col(portfolio_return_column).alias("holding_return"),
            )
            for multiplier in cost_multipliers:
                nav, portfolio_metrics = simulate_diagnostic_factor_portfolio(
                    targets=targets,
                    periods=periods,
                    holding_outcomes=holding_outcomes,
                    costs=costs,
                    multiplier=multiplier,
                    initial_cash=initial_cash,
                    annualization_periods=portfolio_annualization_periods,
                )
                nav_frames.append(
                    nav.with_columns(
                        pl.lit(factor).alias("factor"),
                        pl.lit(fold.fold).alias("fold"),
                        pl.lit(float(multiplier)).alias("cost_multiplier"),
                    )
                )
                metric_row: dict[str, object] = {
                    "factor": factor,
                    "fold": fold.fold,
                    "direction": direction,
                    "cost_multiplier": float(multiplier),
                    "validation_rank_ic": abs(
                        float(validation_metrics["rank_ic_mean"])
                    ),
                    "test_rank_ic": float(test20_metrics["rank_ic_mean"]),
                    "test_ic_dates": int(test20_metrics["dates"]),
                    **portfolio_metrics,
                }
                if fixed_direction is not None:
                    metric_row["validation_observed_direction"] = (
                        validation_observed_direction
                    )
                metric_rows.append(metric_row)
    return {
        "daily_ic": pl.concat(daily_frames).sort(
            "fold", "period", "factor", "horizon", "trade_date"
        ),
        "group_returns": pl.concat(group_frames).sort(
            "fold", "period", "factor", "horizon", "trade_date", "group"
        ),
        "fold_metrics": pl.DataFrame(metric_rows).sort("factor", "fold", "cost_multiplier"),
        "targets": pl.concat(target_frames).sort("as_of", "strategy", "symbol"),
        "portfolio_nav": pl.concat(nav_frames).sort("factor", "fold", "cost_multiplier", "as_of"),
    }


def summarize_factors(
    metrics: pl.DataFrame,
    *,
    factors: tuple[str, ...],
    admission: Mapping[str, Any],
) -> pl.DataFrame:
    """Apply pre-registered research thresholds without PAPER promotion."""
    rows: list[dict[str, object]] = []
    for factor in factors:
        one = metrics.filter((pl.col("factor") == factor) & (pl.col("cost_multiplier") == 1.0))
        two = metrics.filter((pl.col("factor") == factor) & (pl.col("cost_multiplier") == 2.0))
        test_ics = [float(value) for value in one.get_column("test_rank_ic")]
        directions = [int(value) for value in one.get_column("direction")]
        mean_ic = sum(test_ics) / len(test_ics)
        positive_folds = sum(value > 0 for value in test_ics)
        direction_consistent = len(set(directions)) == 1
        one_x_return = (
            math.prod(1.0 + float(value) for value in one.get_column("total_return")) - 1.0
        )
        two_x_return = (
            math.prod(1.0 + float(value) for value in two.get_column("total_return")) - 1.0
        )
        passed = (
            mean_ic >= float(admission["minimum_mean_test_rank_ic"])
            and positive_folds >= cast(int, admission["minimum_positive_test_folds"])
            and (direction_consistent or not cast(bool, admission["require_direction_consistency"]))
            and (two_x_return > 0 or not cast(bool, admission["require_positive_2x_cost_return"]))
        )
        rows.append(
            {
                "factor": factor,
                "mean_test_rank_ic": mean_ic,
                "positive_test_folds": positive_folds,
                "direction_consistent": direction_consistent,
                "one_x_chained_return": one_x_return,
                "two_x_chained_return": two_x_return,
                "research_status": "RESEARCH_ONLY" if passed else "REJECTED",
            }
        )
    return pl.DataFrame(rows).sort("factor")


def evaluate_factor_coverage(
    panel: pl.DataFrame,
    *,
    factors: tuple[str, ...],
    start_date: dt.date,
    end_date: dt.date,
    folds: tuple[ResearchFoldV1, ...],
    rebalance_every_sessions: int,
    minimum_rebalance_symbols: int,
    minimum_median_coverage: float,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Measure all-date and pre-registered rebalance-date factor coverage."""
    if (
        not isinstance(panel, pl.DataFrame)
        or panel.is_empty()
        or type(factors) is not tuple
        or not factors
        or any(type(name) is not str or name not in panel.columns for name in factors)
        or type(start_date) is not dt.date
        or type(end_date) is not dt.date
        or end_date < start_date
        or type(folds) is not tuple
        or not folds
        or any(type(fold) is not ResearchFoldV1 for fold in folds)
        or type(rebalance_every_sessions) is not int
        or rebalance_every_sessions <= 0
        or type(minimum_rebalance_symbols) is not int
        or minimum_rebalance_symbols < 2
        or type(minimum_median_coverage) is not float
        or not math.isfinite(minimum_median_coverage)
        or not 0 < minimum_median_coverage <= 1
        or "exit_date_20" not in panel.columns
    ):
        raise ValueError("invalid factor coverage request")
    research = panel.filter(
        pl.col("trade_date").is_between(start_date, end_date, closed="both")
    )
    if research.is_empty():
        raise ValueError("factor coverage research window is empty")
    scheduled_dates = tuple(
        date
        for fold in folds
        for date in _scheduled_rebalance_dates(
            research,
            fold=fold,
            rebalance_every_sessions=rebalance_every_sessions,
        )
    )
    daily_frames: list[pl.DataFrame] = []
    summary_rows: list[dict[str, object]] = []
    for factor in factors:
        valid = pl.col(factor).is_not_null() & pl.col(factor).is_finite()
        daily = (
            research.group_by("trade_date")
            .agg(
                pl.len().alias("eligible_rows"),
                valid.fill_null(False).sum().alias("valid_rows"),
            )
            .with_columns(
                (pl.col("valid_rows") / pl.col("eligible_rows")).alias("coverage"),
                pl.lit(factor).alias("factor"),
                pl.col("trade_date")
                .is_in(scheduled_dates)
                .alias("scheduled_rebalance"),
            )
            .select(
                "factor",
                "trade_date",
                "eligible_rows",
                "valid_rows",
                "coverage",
                "scheduled_rebalance",
            )
            .sort("factor", "trade_date")
        )
        scheduled = daily.filter(pl.col("scheduled_rebalance"))
        minimum_valid_rows = (
            cast(int, scheduled.get_column("valid_rows").min())
            if not scheduled.is_empty()
            else 0
        )
        median_coverage = cast(float, daily.get_column("coverage").median())
        summary_rows.append(
            {
                "factor": factor,
                "dates": daily.height,
                "scheduled_rebalance_dates": len(scheduled_dates),
                "minimum_rebalance_valid_rows": minimum_valid_rows,
                "median_coverage": median_coverage,
                "coverage_passed": minimum_valid_rows >= minimum_rebalance_symbols
                and median_coverage >= minimum_median_coverage,
            }
        )
        daily_frames.append(daily)
    return (
        pl.concat(daily_frames).sort("factor", "trade_date"),
        pl.DataFrame(summary_rows).sort("factor"),
    )


def evaluate_rebalance_schedule_alignment(
    panel: pl.DataFrame,
    targets: pl.DataFrame,
    *,
    factors: tuple[str, ...],
    folds: tuple[ResearchFoldV1, ...],
    rebalance_every_sessions: int,
) -> pl.DataFrame:
    """Compare emitted target dates with the factor-independent frozen schedule."""
    if (
        not isinstance(panel, pl.DataFrame)
        or panel.is_empty()
        or "trade_date" not in panel.columns
        or "exit_date_20" not in panel.columns
        or not isinstance(targets, pl.DataFrame)
        or targets.is_empty()
        or not {"as_of", "factor", "fold"}.issubset(targets.columns)
        or type(factors) is not tuple
        or not factors
        or any(type(name) is not str for name in factors)
        or type(folds) is not tuple
        or not folds
        or any(type(fold) is not ResearchFoldV1 for fold in folds)
        or type(rebalance_every_sessions) is not int
        or rebalance_every_sessions <= 0
    ):
        raise ValueError("invalid rebalance schedule alignment request")
    rows: list[dict[str, object]] = []
    for factor in factors:
        for fold in folds:
            expected = _scheduled_rebalance_dates(
                panel,
                fold=fold,
                rebalance_every_sessions=rebalance_every_sessions,
            )
            actual = tuple(
                targets.filter(
                    (pl.col("factor") == factor) & (pl.col("fold") == fold.fold)
                )
                .get_column("as_of")
                .unique()
                .sort()
                .to_list()
            )
            expected_set = set(expected)
            actual_set = set(actual)
            missing_dates = tuple(sorted(expected_set - actual_set))
            unexpected_dates = tuple(sorted(actual_set - expected_set))
            rows.append(
                {
                    "factor": factor,
                    "fold": fold.fold,
                    "expected_rebalance_dates": len(expected),
                    "actual_rebalance_dates": len(actual),
                    "missing_rebalance_dates": len(missing_dates),
                    "unexpected_rebalance_dates": len(unexpected_dates),
                    "missing_dates": missing_dates,
                    "unexpected_dates": unexpected_dates,
                    "schedule_aligned": actual == expected,
                }
            )
    return pl.DataFrame(rows).sort("factor", "fold")


def apply_market_risk_admission_gates(
    summary: pl.DataFrame,
    *,
    fold_metrics: pl.DataFrame,
    redundancy_summary: pl.DataFrame,
    coverage_summary: pl.DataFrame,
    schedule_alignment: pl.DataFrame,
    expected_direction: int,
    maximum_median_absolute_rank_correlation: float,
) -> pl.DataFrame:
    """Apply expected-direction, coverage, and redundancy gates to market risk."""
    if (
        not isinstance(summary, pl.DataFrame)
        or summary.is_empty()
        or not isinstance(fold_metrics, pl.DataFrame)
        or fold_metrics.is_empty()
        or not isinstance(redundancy_summary, pl.DataFrame)
        or redundancy_summary.is_empty()
        or not isinstance(coverage_summary, pl.DataFrame)
        or coverage_summary.is_empty()
        or not isinstance(schedule_alignment, pl.DataFrame)
        or schedule_alignment.is_empty()
        or expected_direction not in {-1, 1}
        or type(maximum_median_absolute_rank_correlation) is not float
        or not 0 < maximum_median_absolute_rank_correlation < 1
    ):
        raise ValueError("invalid market-risk admission gate request")
    directions = (
        fold_metrics.filter(pl.col("cost_multiplier") == 1.0)
        .group_by("factor")
        .agg(
            pl.col("direction").n_unique().alias("observed_direction_count"),
            pl.col("direction").first().alias("observed_direction"),
        )
    )
    redundancy = _aggregate_redundancy_by_factor(summary, redundancy_summary)
    schedule = schedule_alignment.group_by("factor").agg(
        pl.col("schedule_aligned").all().alias("schedule_alignment_passed")
    )
    drop_columns = [
        column
        for column in ("max_median_abs_rank_corr", "combination_eligible")
        if column in summary.columns
    ]
    summary_base = summary.drop(drop_columns) if drop_columns else summary
    joined = (
        summary_base
        .join(
            directions,
            on="factor",
            how="left",
            validate="1:1",
            maintain_order="left",
        )
        .join(
            redundancy,
            on="factor",
            how="left",
            validate="1:1",
            maintain_order="left",
        )
        .join(
            coverage_summary,
            on="factor",
            how="left",
            validate="1:1",
            maintain_order="left",
        )
        .join(
            schedule,
            on="factor",
            how="left",
            validate="1:1",
            maintain_order="left",
        )
        .with_columns(
            pl.lit(expected_direction).alias("expected_direction"),
            (
                (pl.col("observed_direction_count") == 1)
                & (pl.col("observed_direction") == expected_direction)
            ).alias("expected_direction_passed"),
            (
                pl.col("max_median_abs_rank_corr").is_not_null()
                & (
                    pl.col("max_median_abs_rank_corr")
                    < maximum_median_absolute_rank_correlation
                )
            ).alias("redundancy_passed"),
        )
        .with_columns(pl.col("redundancy_passed").alias("combination_eligible"))
        .with_columns(
            pl.when(
                (pl.col("research_status") == "RESEARCH_ONLY")
                & pl.col("expected_direction_passed")
                & pl.col("redundancy_passed")
                & pl.col("coverage_passed")
                & pl.col("schedule_alignment_passed")
            )
            .then(pl.lit("RESEARCH_ONLY"))
            .otherwise(pl.lit("REJECTED"))
            .alias("research_status")
        )
    )
    return joined.sort("factor")


def apply_fourth_batch_admission_gates(
    summary: pl.DataFrame,
    *,
    redundancy_summary: pl.DataFrame,
    coverage_summary: pl.DataFrame,
    schedule_alignment: pl.DataFrame,
    maximum_median_absolute_rank_correlation: float,
) -> pl.DataFrame:
    """Fail closed on coverage, redundancy and target-schedule alignment."""
    if (
        not isinstance(summary, pl.DataFrame)
        or summary.is_empty()
        or not isinstance(redundancy_summary, pl.DataFrame)
        or redundancy_summary.is_empty()
        or not isinstance(coverage_summary, pl.DataFrame)
        or coverage_summary.is_empty()
        or not isinstance(schedule_alignment, pl.DataFrame)
        or schedule_alignment.is_empty()
        or type(maximum_median_absolute_rank_correlation) is not float
        or not 0 < maximum_median_absolute_rank_correlation < 1
    ):
        raise ValueError("invalid fourth-batch admission gate request")
    redundancy = _aggregate_redundancy_by_factor(summary, redundancy_summary)
    schedule = schedule_alignment.group_by("factor").agg(
        pl.col("schedule_aligned").all().alias("schedule_alignment_passed")
    )
    drop_columns = [
        column
        for column in ("max_median_abs_rank_corr", "combination_eligible")
        if column in summary.columns
    ]
    summary_base = summary.drop(drop_columns) if drop_columns else summary
    return (
        summary_base.join(
            redundancy,
            on="factor",
            how="left",
            validate="1:1",
            maintain_order="left",
        )
        .join(
            coverage_summary,
            on="factor",
            how="left",
            validate="1:1",
            maintain_order="left",
        )
        .join(
            schedule,
            on="factor",
            how="left",
            validate="1:1",
            maintain_order="left",
        )
        .with_columns(
            (
                pl.col("max_median_abs_rank_corr").is_not_null()
                & (
                    pl.col("max_median_abs_rank_corr")
                    < maximum_median_absolute_rank_correlation
                )
            ).alias("redundancy_passed")
        )
        .with_columns(pl.col("redundancy_passed").alias("combination_eligible"))
        .with_columns(
            pl.when(
                (pl.col("research_status") == "RESEARCH_ONLY")
                & pl.col("redundancy_passed")
                & pl.col("coverage_passed")
                & pl.col("schedule_alignment_passed")
            )
            .then(pl.lit("RESEARCH_ONLY"))
            .otherwise(pl.lit("REJECTED"))
            .alias("research_status")
        )
        .sort("factor")
    )


def _planned_test_signal_dates(
    panel: pl.DataFrame, *, fold: ResearchFoldV1, horizon: int
) -> tuple[dt.date, ...] | None:
    exit_date_column = f"exit_date_{horizon}"
    if (
        exit_date_column not in panel.columns
        or "trade_date" not in panel.columns
        or panel.is_empty()
    ):
        return None
    window = panel.filter(
        pl.col("trade_date").is_between(
            fold.test_start, fold.test_end, closed="both"
        )
    )
    if window.is_empty():
        return None
    date_plan = (
        window.group_by("trade_date")
        .agg(
            pl.len().alias("_rows"),
            pl.col(exit_date_column).null_count().alias("_exit_nulls"),
            pl.col(exit_date_column).drop_nulls().n_unique().alias("_exit_values"),
            pl.col(exit_date_column).drop_nulls().first().alias("_exit_date"),
        )
        .sort("trade_date")
    )
    dates: list[dt.date] = []
    boundary_started = False
    for row in date_plan.iter_rows(named=True):
        trade_date = row["trade_date"]
        row_count = row["_rows"]
        null_count = row["_exit_nulls"]
        value_count = row["_exit_values"]
        planned_exit = row["_exit_date"]
        if (
            type(trade_date) is not dt.date
            or type(row_count) is not int
            or type(null_count) is not int
            or type(value_count) is not int
            or null_count not in {0, row_count}
            or value_count > 1
        ):
            return None
        is_boundary = null_count == row_count or (
            planned_exit is not None and planned_exit > fold.test_end
        )
        if is_boundary:
            boundary_started = True
            continue
        if (
            boundary_started
            or planned_exit is None
            or type(planned_exit) is not dt.date
            or planned_exit < trade_date
        ):
            return None
        dates.append(trade_date)
    return tuple(dates) if dates else None


def _primary_monotonicity_row(
    *,
    factor: str,
    fold: int,
    signal_dates: int,
    means: Mapping[int, float] | None,
    invalid_reason: str | None,
    expected_direction: int,
) -> dict[str, object]:
    values: tuple[float | None, float | None, float | None, float | None, float | None]
    if means is None:
        values = (None, None, None, None, None)
        comparisons = (False, False, False, False)
    else:
        values = cast(
            tuple[float | None, float | None, float | None, float | None, float | None],
            tuple(means.get(group) for group in range(1, 6)),
        )
        comparison_values: list[bool] = []
        for index in range(4):
            left = values[index]
            right = values[index + 1]
            comparison_values.append(
                left <= right if left is not None and right is not None else False
            )
        comparisons = cast(
            tuple[bool, bool, bool, bool], tuple(comparison_values)
        )
    return {
        "factor": factor,
        "fold": fold,
        "period": "test",
        "horizon": 20,
        "expected_direction": expected_direction,
        "signal_dates": signal_dates,
        "group_1_mean_return": values[0],
        "group_2_mean_return": values[1],
        "group_3_mean_return": values[2],
        "group_4_mean_return": values[3],
        "group_5_mean_return": values[4],
        "group_1_le_group_2": comparisons[0],
        "group_2_le_group_3": comparisons[1],
        "group_3_le_group_4": comparisons[2],
        "group_4_le_group_5": comparisons[3],
        "monotonicity_passed": invalid_reason is None and all(comparisons),
        "invalid_reason": invalid_reason,
    }


def evaluate_primary_group_monotonicity(
    group_returns: pl.DataFrame,
    *,
    panel: pl.DataFrame,
    factor: str,
    folds: tuple[ResearchFoldV1, ...],
    minimum_symbols: int,
    expected_direction: int,
) -> pl.DataFrame:
    """Validate and aggregate the frozen MAX test horizon-20 five-group gate."""
    required_columns = {
        "factor",
        "fold",
        "period",
        "horizon",
        "direction",
        "trade_date",
        "group",
        "n_symbols",
        "mean_return",
        "factor_count",
        "paired_count",
        "coverage_numerator",
        "coverage_denominator",
        "coverage_status",
    }
    if (
        not isinstance(group_returns, pl.DataFrame)
        or not isinstance(panel, pl.DataFrame)
        or type(factor) is not str
        or not factor
        or type(folds) is not tuple
        or len(folds) != 3
        or any(type(item) is not ResearchFoldV1 for item in folds)
        or tuple(item.fold for item in folds) != (1, 2, 3)
        or type(minimum_symbols) is not int
        or minimum_symbols < 2
        or expected_direction != -1
        or not required_columns.issubset(group_returns.columns)
    ):
        raise ValueError("invalid primary group monotonicity request")

    valid_rows: list[dict[str, object]] = []
    result_rows: list[dict[str, object]] = []
    for fold in folds:
        expected_dates = _planned_test_signal_dates(panel, fold=fold, horizon=20)
        planned_dates = () if expected_dates is None else expected_dates
        selected = group_returns.filter(
            (pl.col("factor") == factor)
            & (pl.col("fold") == fold.fold)
            & (pl.col("period") == "test")
            & (pl.col("horizon") == 20)
        )
        actual_rows = selected.to_dicts()
        invalid_reason: str | None = None
        if expected_dates is None:
            invalid_reason = "missing_planned_test_dates"
        elif any(type(row.get("trade_date")) is not dt.date for row in actual_rows):
            invalid_reason = "test_signal_date_grid_mismatch"
        elif (
            tuple(
                sorted({cast(dt.date, row["trade_date"]) for row in actual_rows})
            )
            != planned_dates
        ):
            invalid_reason = "test_signal_date_grid_mismatch"
        elif any(type(row.get("group")) is not int for row in actual_rows):
            invalid_reason = "group_label_type_mismatch"
        elif {row.get("group") for row in actual_rows} != set(range(1, 6)):
            invalid_reason = "test_group_grid_mismatch"
        else:
            key_counts: dict[tuple[object, object], int] = {}
            for row in actual_rows:
                key = (row.get("trade_date"), row.get("group"))
                key_counts[key] = key_counts.get(key, 0) + 1
            if any(count != 1 for count in key_counts.values()):
                invalid_reason = "duplicate_test_group_row"
            elif len(actual_rows) != len(planned_dates) * 5:
                invalid_reason = "test_group_grid_mismatch"

        date_totals: dict[object, dict[str, int]] = {}
        means_by_group: dict[int, list[float]] = {group: [] for group in range(1, 6)}
        if invalid_reason is None:
            for row in actual_rows:
                if (
                    row.get("direction") != expected_direction
                    or row.get("coverage_status") != "PASS"
                ):
                    invalid_reason = "coverage_or_direction_failed"
                    break
                count_values = (
                    row.get("n_symbols"),
                    row.get("factor_count"),
                    row.get("paired_count"),
                    row.get("coverage_numerator"),
                    row.get("coverage_denominator"),
                )
                mean_return = row.get("mean_return")
                if any(type(value) is not int for value in count_values) or (
                    type(mean_return) not in {int, float}
                    or isinstance(mean_return, bool)
                    or not math.isfinite(float(cast(int | float, mean_return)))
                ):
                    invalid_reason = "non_finite_or_invalid_group_value"
                    break
                if (
                    int(row["n_symbols"]) <= 0
                    or int(row["factor_count"]) <= 0
                    or int(row["paired_count"]) <= 0
                    or int(row["coverage_numerator"]) != int(row["paired_count"])
                    or int(row["coverage_denominator"]) != int(row["factor_count"])
                ):
                    invalid_reason = "group_coverage_incomplete"
                    break
                date = row.get("trade_date")
                if date not in date_totals:
                    date_totals[date] = {
                        "n_symbols": 0,
                        "factor_count": 0,
                        "paired_count": 0,
                    }
                date_totals[date]["n_symbols"] += int(row["n_symbols"])
                date_totals[date]["factor_count"] += int(row["factor_count"])
                date_totals[date]["paired_count"] += int(row["paired_count"])
                means_by_group[int(row["group"])].append(
                    float(cast(int | float, mean_return))
                )
            if invalid_reason is None and any(
                totals["n_symbols"] < minimum_symbols
                or totals["factor_count"] < minimum_symbols
                or totals["paired_count"] < minimum_symbols
                for totals in date_totals.values()
            ):
                invalid_reason = "minimum_symbol_contract_failed"
            if invalid_reason is None and any(
                len(values) != len(planned_dates)
                or not all(math.isfinite(value) for value in values)
                for values in means_by_group.values()
            ):
                invalid_reason = "non_finite_or_missing_group_return"

        if invalid_reason is None:
            means = {
                group: sum(values) / len(values)
                for group, values in means_by_group.items()
            }
            fold_rows = [
                row
                for row in actual_rows
                if row.get("trade_date") in set(planned_dates)
            ]
            valid_rows.extend(fold_rows)
        else:
            means = None
        result_rows.append(
            _primary_monotonicity_row(
                factor=factor,
                fold=fold.fold,
                signal_dates=0 if expected_dates is None else len(expected_dates),
                means=means,
                invalid_reason=invalid_reason,
                expected_direction=expected_direction,
            )
        )

    pooled_invalid_reason: str | None = None
    pooled_means: Mapping[int, float] | None = None
    if any(row["invalid_reason"] is not None for row in result_rows):
        pooled_invalid_reason = "fold_monotonicity_input_invalid"
    else:
        pooled_signal_keys = {
            (row.get("fold"), row.get("trade_date")) for row in valid_rows
        }
        pooled_dates = [date for _, date in pooled_signal_keys]
        if len(set(pooled_dates)) != len(pooled_signal_keys):
            pooled_invalid_reason = "pooled_signal_date_duplicate"
        else:
            pooled_values: dict[int, list[float]] = {group: [] for group in range(1, 6)}
            for row in valid_rows:
                group = row.get("group")
                if type(group) is not int or group not in pooled_values:
                    pooled_invalid_reason = "pooled_group_grid_mismatch"
                    break
                value = row.get("mean_return")
                if (
                    type(value) not in {int, float}
                    or isinstance(value, bool)
                    or not math.isfinite(float(cast(int | float, value)))
                ):
                    pooled_invalid_reason = "pooled_non_finite_group_return"
                    break
                pooled_values[group].append(float(cast(int | float, value)))
            if pooled_invalid_reason is None:
                pooled_means = {
                    group: sum(values) / len(values)
                    for group, values in pooled_values.items()
                }
    result_rows.append(
        _primary_monotonicity_row(
            factor=factor,
            fold=0,
            signal_dates=len(valid_rows) // 5 if pooled_invalid_reason is None else 0,
            means=pooled_means,
            invalid_reason=pooled_invalid_reason,
            expected_direction=expected_direction,
        )
    )
    return pl.DataFrame(result_rows).sort("fold")


def apply_fifth_batch_admission_gates(
    summary: pl.DataFrame,
    *,
    fold_metrics: pl.DataFrame,
    redundancy_summary: pl.DataFrame,
    coverage_summary: pl.DataFrame,
    schedule_alignment: pl.DataFrame,
    expected_direction: int,
    maximum_median_absolute_rank_correlation: float,
    primary_group_monotonicity: pl.DataFrame,
) -> pl.DataFrame:
    """Apply fixed-direction, coverage, redundancy and schedule gates to MAX."""
    monotonicity_columns = {
        "factor",
        "fold",
        "period",
        "horizon",
        "expected_direction",
        "monotonicity_passed",
    }
    if (
        not isinstance(summary, pl.DataFrame)
        or summary.is_empty()
        or not isinstance(fold_metrics, pl.DataFrame)
        or fold_metrics.is_empty()
        or not {
            "factor",
            "cost_multiplier",
            "direction",
            "validation_observed_direction",
        }.issubset(fold_metrics.columns)
        or not isinstance(redundancy_summary, pl.DataFrame)
        or redundancy_summary.is_empty()
        or not isinstance(coverage_summary, pl.DataFrame)
        or coverage_summary.is_empty()
        or not isinstance(schedule_alignment, pl.DataFrame)
        or schedule_alignment.is_empty()
        or not isinstance(primary_group_monotonicity, pl.DataFrame)
        or primary_group_monotonicity.is_empty()
        or not monotonicity_columns.issubset(primary_group_monotonicity.columns)
        or expected_direction not in {-1, 1}
        or expected_direction != -1
        or type(maximum_median_absolute_rank_correlation) is not float
        or not 0 < maximum_median_absolute_rank_correlation < 1
    ):
        raise ValueError("invalid fifth-batch admission gate request")
    directions = (
        fold_metrics.filter(pl.col("cost_multiplier") == 1.0)
        .group_by("factor")
        .agg(
            pl.col("direction").n_unique().alias("selected_direction_count"),
            pl.col("direction").first().alias("selected_direction"),
            (
                pl.col("validation_observed_direction") == expected_direction
            ).all().alias("validation_direction_passed"),
        )
    )
    redundancy = _aggregate_redundancy_by_factor(summary, redundancy_summary)
    schedule = schedule_alignment.group_by("factor").agg(
        pl.col("schedule_aligned").all().alias("schedule_alignment_passed")
    )
    monotonicity_rows: list[dict[str, object]] = []
    for factor in summary.get_column("factor").to_list():
        one = primary_group_monotonicity.filter(
            (pl.col("factor") == factor)
            & (pl.col("period") == "test")
            & (pl.col("horizon") == 20)
            & (pl.col("expected_direction") == expected_direction)
        )
        fold_rows = one.filter(pl.col("fold") > 0)
        pooled_rows = one.filter(pl.col("fold") == 0)
        fold_ids = tuple(sorted(fold_rows.get_column("fold").to_list()))
        fold_passed = sum(
            bool(value) for value in fold_rows.get_column("monotonicity_passed").to_list()
        )
        pooled_passed = (
            pooled_rows.height == 1
            and bool(pooled_rows.get_column("monotonicity_passed").item())
        )
        monotonicity_rows.append(
            {
                "factor": factor,
                "primary_monotonicity_fold_count": fold_rows.height,
                "primary_monotonicity_passed_folds": fold_passed,
                "primary_monotonicity_required_folds": 2,
                "primary_monotonicity_pooled_passed": pooled_passed,
                "primary_monotonicity_passed": (
                    fold_ids == (1, 2, 3)
                    and fold_passed >= 2
                    and pooled_passed
                ),
            }
        )
    monotonicity = pl.DataFrame(monotonicity_rows)
    drop_columns = [
        column
        for column in ("max_median_abs_rank_corr", "combination_eligible")
        if column in summary.columns
    ]
    summary_base = summary.drop(drop_columns) if drop_columns else summary
    return (
        summary_base.join(
            directions,
            on="factor",
            how="left",
            validate="1:1",
            maintain_order="left",
        )
        .join(
            redundancy,
            on="factor",
            how="left",
            validate="1:1",
            maintain_order="left",
        )
        .join(
            coverage_summary,
            on="factor",
            how="left",
            validate="1:1",
            maintain_order="left",
        )
        .join(
            schedule,
            on="factor",
            how="left",
            validate="1:1",
            maintain_order="left",
        )
        .join(
            monotonicity,
            on="factor",
            how="left",
            validate="1:1",
            maintain_order="left",
        )
        .with_columns(
            pl.lit(expected_direction).alias("expected_direction"),
            (
                (pl.col("selected_direction_count") == 1)
                & (pl.col("selected_direction") == expected_direction)
            ).alias("fixed_direction_passed"),
            (
                pl.col("max_median_abs_rank_corr").is_not_null()
                & (
                    pl.col("max_median_abs_rank_corr")
                    < maximum_median_absolute_rank_correlation
                )
            ).alias("redundancy_passed"),
        )
        .with_columns(pl.col("redundancy_passed").alias("combination_eligible"))
        .with_columns(
            pl.when(
                (pl.col("research_status") == "RESEARCH_ONLY")
                & pl.col("fixed_direction_passed")
                & pl.col("validation_direction_passed")
                & pl.col("redundancy_passed")
                & pl.col("coverage_passed")
                & pl.col("schedule_alignment_passed")
                & pl.col("primary_monotonicity_passed")
            )
            .then(pl.lit("RESEARCH_ONLY"))
            .otherwise(pl.lit("REJECTED"))
            .alias("research_status")
        )
        .sort("factor")
    )


def _scheduled_rebalance_dates(
    panel: pl.DataFrame,
    *,
    fold: ResearchFoldV1,
    rebalance_every_sessions: int,
) -> tuple[dt.date, ...]:
    return tuple(
        panel.filter(
            pl.col("trade_date").is_between(
                fold.test_start, fold.test_end, closed="both"
            )
            & (pl.col("exit_date_20") <= fold.test_end)
        )
        .get_column("trade_date")
        .unique()
        .sort()
        .to_list()[::rebalance_every_sessions]
    )


def _with_evaluation_identity(
    frame: pl.DataFrame,
    *,
    fold: int,
    period: str,
    factor: str,
    horizon: int,
    direction: int,
) -> pl.DataFrame:
    return frame.with_columns(
        pl.lit(fold).alias("fold"),
        pl.lit(period).alias("period"),
        pl.lit(factor).alias("factor"),
        pl.lit(horizon).alias("horizon"),
        pl.lit(direction).alias("direction"),
    )

