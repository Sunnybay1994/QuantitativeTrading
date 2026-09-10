"""Cross-sectional evaluation and diagnostic portfolios for classic factors."""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping
from decimal import Decimal, localcontext
from typing import cast

import polars as pl

from quant.domain import TargetWeightSchema
from quant.research.m3.contracts import AShareCostPeriod


_GROSS_RETURN_TOLERANCE = Decimal("1e-12")


def evaluate_factor_period(
    panel: pl.DataFrame,
    *,
    factor: str,
    horizon: int,
    start_date: dt.date,
    end_date: dt.date,
    minimum_symbols: int,
    groups: int = 5,
    direction: int = 1,
    newey_west_lag: int | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame, dict[str, float | int]]:
    """Compute daily IC, group returns, and aggregate statistics for one period."""
    label = f"label_{horizon}"
    exit_date = f"exit_date_{horizon}"
    if (
        factor not in panel.columns
        or label not in panel.columns
        or exit_date not in panel.columns
        or type(horizon) is not int
        or horizon <= 0
        or type(start_date) is not dt.date
        or type(end_date) is not dt.date
        or end_date < start_date
        or type(minimum_symbols) is not int
        or minimum_symbols < 2
        or type(groups) is not int
        or groups < 2
        or direction not in {-1, 1}
        or (newey_west_lag is not None and (type(newey_west_lag) is not int or newey_west_lag < 0))
    ):
        raise ValueError("invalid factor evaluation request")
    window = panel.filter(
        pl.col("trade_date").is_between(start_date, end_date, closed="both")
    ).select("trade_date", "symbol", factor, label, exit_date)
    if window.is_empty():
        raise ValueError("factor period has no planned dates")

    date_plan = (
        window.group_by("trade_date")
        .agg(
            pl.len().alias("_rows"),
            pl.col(exit_date).null_count().alias("_exit_nulls"),
            pl.col(exit_date).drop_nulls().n_unique().alias("_exit_values"),
            pl.col(exit_date).drop_nulls().first().alias("_exit_date"),
        )
        .sort("trade_date")
    )
    evaluable_dates: list[dt.date] = []
    boundary_started = False
    for row in date_plan.iter_rows(named=True):
        trade_date = cast(dt.date, row["trade_date"])
        row_count = cast(int, row["_rows"])
        null_count = cast(int, row["_exit_nulls"])
        value_count = cast(int, row["_exit_values"])
        planned_exit = cast(dt.date | None, row["_exit_date"])
        if null_count not in {0, row_count} or value_count > 1:
            raise ValueError("factor period exit-date plan is inconsistent")
        is_boundary = null_count == row_count or (
            planned_exit is not None and planned_exit > end_date
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
            raise ValueError("factor period exit-date plan is inconsistent")
        evaluable_dates.append(trade_date)
    if not evaluable_dates:
        raise ValueError("factor period has no computable IC dates")

    cohort = (
        window.filter(
            pl.col("trade_date").is_in(evaluable_dates)
            & pl.col(factor).is_not_null()
            & pl.col(factor).is_finite()
        )
        .select(
            "trade_date",
            "symbol",
            (pl.col(factor) * direction).alias("score"),
            pl.col(label).alias("label"),
        )
        .sort("trade_date", "symbol")
    )
    factor_counts = (
        cohort.group_by("trade_date").agg(pl.len().alias("factor_count")).sort("trade_date")
    )
    if (
        factor_counts.height != len(evaluable_dates)
        or cast(int, factor_counts.get_column("factor_count").min())
        < minimum_symbols
    ):
        counts = dict(factor_counts.iter_rows())
        deficient = [(date, counts.get(date, 0)) for date in evaluable_dates
                     if counts.get(date, 0) < minimum_symbols]
        examples = ', '.join(f'{date}:{count}' for date, count in deficient[:5])
        raise ValueError(f"factor period signal cohort is incomplete: {factor}, "
                         f"minimum={minimum_symbols}, deficient_dates={len(deficient)}, "
                         f"examples=[{examples}]")
    cohort = (
        cohort.join(factor_counts, on="trade_date", how="left", validate="m:1")
        .with_columns(
            pl.col("score").rank("average").over("trade_date").alias("score_rank")
        )
        .with_columns(
            (
                (
                    (pl.col("score_rank") - 1.0)
                    * groups
                    / pl.col("factor_count")
                )
                .floor()
                .cast(pl.Int64)
                + 1
            ).alias("group")
        )
    )
    paired = cohort.filter(pl.col("label").is_not_null() & pl.col("label").is_finite())
    paired_counts = paired.group_by("trade_date").agg(pl.len().alias("paired_count"))
    coverage = (
        factor_counts.join(paired_counts, on="trade_date", how="left", validate="1:1")
        .with_columns(pl.col("paired_count").fill_null(0).cast(pl.UInt32))
        .sort("trade_date")
    )
    if cast(int, coverage.get_column("paired_count").min()) < minimum_symbols:
        raise ValueError("factor period paired outcomes are incomplete")
    paired = (
        paired.join(
            coverage.select("trade_date", "paired_count"),
            on="trade_date",
            how="left",
            validate="m:1",
        )
        .with_columns(
            pl.col("score").rank("average").over("trade_date").alias("paired_score_rank"),
            pl.col("label").rank("average").over("trade_date").alias("label_rank"),
        )
    )
    daily = (
        paired.group_by("trade_date")
        .agg(
            pl.len().alias("n_symbols"),
            pl.corr("score", "label").alias("pearson_ic"),
            pl.corr("paired_score_rank", "label_rank").alias("rank_ic"),
        )
        .join(coverage, on="trade_date", how="left", validate="1:1")
        .with_columns(
            pl.col("paired_count").alias("coverage_numerator"),
            pl.col("factor_count").alias("coverage_denominator"),
            pl.lit("PASS").alias("coverage_status"),
        )
        .select(
            "trade_date",
            "n_symbols",
            "pearson_ic",
            "rank_ic",
            "factor_count",
            "paired_count",
            "coverage_numerator",
            "coverage_denominator",
            "coverage_status",
        )
        .sort("trade_date")
    )
    if (
        daily.height != len(evaluable_dates)
        or daily.get_column("trade_date").to_list() != evaluable_dates
        or not daily.get_column("pearson_ic").is_finite().all()
        or not daily.get_column("rank_ic").is_finite().all()
    ):
        raise ValueError("factor period has a non-computable planned date")

    group_grid = pl.DataFrame({"trade_date": evaluable_dates}).join(
        pl.DataFrame({"group": range(1, groups + 1)}), how="cross"
    )
    cohort_groups = cohort.group_by("trade_date", "group").agg(
        pl.len().alias("factor_count")
    )
    paired_groups = paired.group_by("trade_date", "group").agg(
        pl.len().alias("paired_count"), pl.col("label").mean().alias("mean_return")
    )
    group_returns = (
        group_grid.join(
            cohort_groups,
            on=["trade_date", "group"],
            how="left",
            validate="1:1",
        )
        .join(
            paired_groups,
            on=["trade_date", "group"],
            how="left",
            validate="1:1",
        )
        .with_columns(
            pl.col("factor_count").fill_null(0).cast(pl.UInt32),
            pl.col("paired_count").fill_null(0).cast(pl.UInt32),
        )
        .with_columns(
            pl.col("paired_count").alias("n_symbols"),
            pl.col("paired_count").alias("coverage_numerator"),
            pl.col("factor_count").alias("coverage_denominator"),
            pl.when(pl.col("factor_count") == 0)
            .then(pl.lit("EMPTY_FACTOR_GROUP"))
            .when(pl.col("paired_count") == 0)
            .then(pl.lit("NO_PAIRED_LABELS"))
            .otherwise(pl.lit("PASS"))
            .alias("coverage_status"),
        )
        .select(
            "trade_date",
            "group",
            "n_symbols",
            "mean_return",
            "factor_count",
            "paired_count",
            "coverage_numerator",
            "coverage_denominator",
            "coverage_status",
        )
        .sort("trade_date", "group")
    )
    rank_values = [float(value) for value in daily.get_column("rank_ic")]
    rank_mean = sum(rank_values) / len(rank_values)
    rank_std = _sample_std(rank_values)
    return (
        daily,
        group_returns,
        {
            "dates": daily.height,
            "mean_symbols": cast(float, daily.get_column("n_symbols").mean()),
            "pearson_ic_mean": cast(float, daily.get_column("pearson_ic").mean()),
            "rank_ic_mean": rank_mean,
            "rank_ic_std": rank_std,
            "rank_icir": rank_mean / rank_std if rank_std > 0 else 0.0,
            "rank_ic_newey_west_t": newey_west_t_statistic(
                rank_values,
                lag=min(
                    horizon if newey_west_lag is None else newey_west_lag,
                    max(0, len(rank_values) - 1),
                ),
            ),
        },
    )


def newey_west_t_statistic(values: list[float], *, lag: int) -> float:
    """Return a Bartlett-kernel Newey-West t-statistic for the sample mean."""
    if (
        not values
        or type(lag) is not int
        or lag < 0
        or lag >= len(values)
        or any(not math.isfinite(value) for value in values)
    ):
        raise ValueError("invalid Newey-West inputs")
    count = len(values)
    mean = sum(values) / count
    centered = [value - mean for value in values]
    long_run = sum(value * value for value in centered) / count
    for offset in range(1, lag + 1):
        covariance = (
            sum(centered[index] * centered[index - offset] for index in range(offset, count))
            / count
        )
        weight = 1.0 - offset / (lag + 1.0)
        long_run += 2.0 * weight * covariance
    standard_error = math.sqrt(max(0.0, long_run) / count)
    return mean / standard_error if standard_error > 0 else 0.0


def evaluate_factor_redundancy(
    panel: pl.DataFrame,
    *,
    factors: tuple[str, ...],
    reference_factors: tuple[str, ...],
    start_date: dt.date,
    end_date: dt.date,
    minimum_symbols: int,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Measure daily cross-sectional rank correlation for pre-registered pairs."""
    if (
        not isinstance(panel, pl.DataFrame)
        or panel.is_empty()
        or type(factors) is not tuple
        or not factors
        or len(factors) != len(set(factors))
        or type(reference_factors) is not tuple
        or not reference_factors
        or len(reference_factors) != len(set(reference_factors))
        or set(factors) & set(reference_factors)
        or any(name not in panel.columns for name in factors + reference_factors)
        or type(start_date) is not dt.date
        or type(end_date) is not dt.date
        or end_date < start_date
        or type(minimum_symbols) is not int
        or minimum_symbols < 2
    ):
        raise ValueError("invalid factor redundancy request")
    ordered_factors = tuple(sorted(factors))
    ordered_references = tuple(sorted(reference_factors))
    pairs = [
        (left, right)
        for index, left in enumerate(ordered_factors)
        for right in ordered_factors[index + 1 :]
    ] + [(left, right) for left in ordered_factors for right in ordered_references]
    daily_frames: list[pl.DataFrame] = []
    for left, right in pairs:
        selected = (
            panel.filter(
                pl.col("trade_date").is_between(start_date, end_date, closed="both")
                & pl.col(left).is_not_null()
                & pl.col(right).is_not_null()
                & pl.col(left).is_finite()
                & pl.col(right).is_finite()
            )
            .select("trade_date", "symbol", left, right)
            .sort("trade_date", "symbol")
        )
        ranked = selected.with_columns(
            pl.len().over("trade_date").alias("n_symbols"),
            pl.col(left).rank("average").over("trade_date").alias("left_rank"),
            pl.col(right).rank("average").over("trade_date").alias("right_rank"),
        ).filter(pl.col("n_symbols") >= minimum_symbols)
        daily = (
            ranked.group_by("trade_date")
            .agg(
                pl.len().alias("n_symbols"),
                pl.corr("left_rank", "right_rank").alias("rank_corr"),
            )
            .filter(pl.col("rank_corr").is_finite())
            .with_columns(
                pl.lit(left).alias("factor_a"),
                pl.lit(right).alias("factor_b"),
            )
            .select("factor_a", "factor_b", "trade_date", "n_symbols", "rank_corr")
        )
        if daily.is_empty():
            raise ValueError("factor redundancy pair has no valid dates")
        daily_frames.append(daily)
    all_daily = pl.concat(daily_frames).sort("factor_a", "factor_b", "trade_date")
    summary = (
        all_daily.group_by("factor_a", "factor_b")
        .agg(
            pl.len().alias("dates"),
            pl.col("rank_corr").median().alias("median_rank_corr"),
            pl.col("rank_corr").abs().median().alias("median_abs_rank_corr"),
        )
        .sort("factor_a", "factor_b")
    )
    return all_daily, summary


def build_diagnostic_factor_targets(
    panel: pl.DataFrame,
    *,
    factor: str,
    direction: int,
    fold: int,
    test_start: dt.date,
    test_end: dt.date,
    top_k: int,
    rebalance_every_sessions: int,
    minimum_symbols: int,
    strategy_name: str,
    strategy_version: str,
    return_column: str = "label_20",
    execution_date_column: str = "execution_date_20",
    exit_date_column: str = "exit_date_20",
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Build targets before validating their explicit holding-period outcomes."""
    if (
        factor not in panel.columns
        or type(return_column) is not str
        or return_column not in panel.columns
        or type(execution_date_column) is not str
        or execution_date_column not in panel.columns
        or type(exit_date_column) is not str
        or exit_date_column not in panel.columns
        or direction not in {-1, 1}
        or type(fold) is not int
        or fold <= 0
        or type(top_k) is not int
        or top_k <= 0
        or type(rebalance_every_sessions) is not int
        or rebalance_every_sessions <= 0
        or minimum_symbols < top_k
        or not strategy_name
        or not strategy_version
    ):
        raise ValueError("invalid diagnostic target request")
    test_panel = panel.filter(
        pl.col("trade_date").is_between(test_start, test_end, closed="both")
    )
    dates = test_panel.get_column("trade_date").unique().sort().to_list()[
        ::rebalance_every_sessions
    ]
    evaluable_dates = set(
        test_panel.filter(
            pl.col(exit_date_column).is_not_null() & (pl.col(exit_date_column) <= test_end)
        )
        .get_column("trade_date")
        .unique()
        .to_list()
    )
    last_evaluable_date = max(evaluable_dates) if evaluable_dates else None
    target_rows: list[dict[str, object]] = []
    period_rows: list[dict[str, object]] = []
    for as_of in dates:
        date_panel = test_panel.filter(pl.col("trade_date") == as_of)
        if as_of not in evaluable_dates:
            if last_evaluable_date is not None and as_of < last_evaluable_date:
                raise ValueError("diagnostic target date plan is incomplete")
            continue
        cross_section = (
            date_panel.filter(pl.col(factor).is_not_null() & pl.col(factor).is_finite())
            .with_columns((pl.col(factor) * direction).alias("_score"))
            .sort("_score", "symbol", descending=[True, False])
        )
        if cross_section.height < minimum_symbols:
            continue
        chosen = cross_section.head(top_k)
        execution_dates = chosen.get_column(execution_date_column).unique().to_list()
        exit_dates = chosen.get_column(exit_date_column).unique().to_list()
        returns = chosen.get_column(return_column)
        if (
            len(execution_dates) != 1
            or len(exit_dates) != 1
            or execution_dates[0] is None
            or exit_dates[0] is None
            or type(execution_dates[0]) is not dt.date
            or type(exit_dates[0]) is not dt.date
            or exit_dates[0] < execution_dates[0]
            or exit_dates[0] > test_end
            or returns.null_count() > 0
            or not returns.is_finite().all()
        ):
            raise ValueError("diagnostic selected target outcomes are invalid")
        weight = 1.0 / top_k
        strategy = f"{strategy_name}_{factor}_f{fold}"
        for symbol in chosen.get_column("symbol"):
            target_rows.append(
                {
                    "as_of": as_of,
                    "strategy": strategy,
                    "strategy_version": strategy_version,
                    "symbol": symbol,
                    "weight": weight,
                    "execution_date": execution_dates[0],
                    "exit_date": exit_dates[0],
                    "factor": factor,
                    "fold": fold,
                }
            )
        period_rows.append(
            {
                "as_of": as_of,
                "execution_date": execution_dates[0],
                "exit_date": exit_dates[0],
                "gross_return": cast(float, chosen.get_column(return_column).mean()),
            }
        )
    if not target_rows:
        raise ValueError("diagnostic targets are empty")
    targets = pl.DataFrame(target_rows).sort("as_of", "strategy", "symbol")
    TargetWeightSchema.validate(
        targets.select("as_of", "strategy", "strategy_version", "symbol", "weight")
    )
    return targets, pl.DataFrame(period_rows).sort("as_of")


def simulate_diagnostic_factor_portfolio(
    *,
    targets: pl.DataFrame,
    periods: pl.DataFrame,
    holding_outcomes: pl.DataFrame,
    costs: tuple[AShareCostPeriod, ...],
    multiplier: Decimal,
    initial_cash: Decimal,
    annualization_periods: float = 252.0 / 20.0,
) -> tuple[pl.DataFrame, dict[str, float]]:
    """Apply target turnover and frozen historical costs to diagnostic returns."""
    if (
        not isinstance(targets, pl.DataFrame)
        or targets.is_empty()
        or not isinstance(periods, pl.DataFrame)
        or periods.is_empty()
        or not isinstance(holding_outcomes, pl.DataFrame)
        or holding_outcomes.is_empty()
        or holding_outcomes.columns != ["as_of", "symbol", "holding_return"]
        or holding_outcomes.schema != {
            "as_of": pl.Date,
            "symbol": pl.String,
            "holding_return": pl.Float64,
        }
        or type(costs) is not tuple
        or not costs
        or any(type(item) is not AShareCostPeriod for item in costs)
        or type(multiplier) is not Decimal
        or not multiplier.is_finite()
        or multiplier <= 0
        or type(initial_cash) is not Decimal
        or not initial_cash.is_finite()
        or initial_cash <= 0
        or type(annualization_periods) is not float
        or not math.isfinite(annualization_periods)
        or annualization_periods <= 0
    ):
        raise ValueError("invalid diagnostic portfolio inputs")
    if (
        targets.select(pl.struct("as_of", "symbol").is_duplicated().any()).item()
        or periods.get_column("as_of").n_unique() != periods.height
        or set(targets.get_column("as_of").to_list())
        != set(periods.get_column("as_of").to_list())
    ):
        raise ValueError("diagnostic portfolio keys are not unique")
    equity = initial_cash
    previous: dict[str, Decimal] = {}
    previous_exit_date: dt.date | None = None
    rows: list[dict[str, object]] = []
    period_returns: list[float] = []
    last_period_start_equity = initial_cash
    with localcontext() as context:
        context.prec = 50
        for period_row in periods.sort("as_of").iter_rows(named=True):
            as_of = period_row["as_of"]
            execution_date = period_row["execution_date"]
            exit_date_value = period_row["exit_date"]
            if (
                type(as_of) is not dt.date
                or type(execution_date) is not dt.date
                or type(exit_date_value) is not dt.date
                or exit_date_value < execution_date
                or (
                    previous_exit_date is not None
                    and previous_exit_date != execution_date
                )
            ):
                raise ValueError("diagnostic holding periods are not contiguous")
            current_frame = targets.filter(pl.col("as_of") == as_of)
            if current_frame.is_empty():
                raise ValueError("diagnostic target period is missing")
            current = {
                symbol: Decimal(str(weight))
                for symbol, weight in current_frame.select("symbol", "weight").iter_rows()
            }
            if (
                len(current) != current_frame.height
                or any(not weight.is_finite() or weight < 0 for weight in current.values())
                or sum(current.values()) > Decimal(1)
            ):
                raise ValueError("diagnostic target weights are invalid")
            selected_outcomes = holding_outcomes.filter(
                (pl.col("as_of") == as_of)
                & pl.col("symbol").is_in(current_frame.get_column("symbol").implode())
            ).sort("symbol")
            if (
                selected_outcomes.height != current_frame.height
                or selected_outcomes.select(
                    pl.struct("as_of", "symbol").is_duplicated().any()
                ).item()
                or selected_outcomes.get_column("holding_return").null_count()
                or not selected_outcomes.get_column("holding_return").is_finite().all()
            ):
                raise ValueError("diagnostic holding outcomes are incomplete")
            returns = {
                symbol: Decimal(str(value))
                for symbol, value in selected_outcomes.select(
                    "symbol", "holding_return"
                ).iter_rows()
            }
            if set(returns) != set(current) or any(
                value < Decimal(-1) for value in returns.values()
            ):
                raise ValueError("diagnostic holding outcomes are invalid")
            start_equity = equity
            cost = _target_change_cost(
                previous,
                current,
                equity=equity,
                date=execution_date,
                multiplier=multiplier,
                costs=costs,
            )
            if cost >= equity:
                raise ValueError("diagnostic portfolio costs exhaust equity")
            gross_return = sum(
                current[symbol] * returns[symbol] for symbol in current
            )
            recorded_value = period_row["gross_return"]
            if type(recorded_value) not in {int, float} or not math.isfinite(
                float(recorded_value)
            ):
                raise ValueError("diagnostic gross return does not match outcomes")
            recorded_gross = Decimal(str(recorded_value))
            if (
                not recorded_gross.is_finite()
                or abs(recorded_gross - gross_return) > _GROSS_RETURN_TOLERANCE
            ):
                raise ValueError("diagnostic gross return does not match outcomes")
            gross_factor = Decimal(1) + gross_return
            if gross_factor <= 0:
                raise ValueError("diagnostic holding return exhausts equity")
            equity = (equity - cost) * gross_factor
            net_return = equity / start_equity - Decimal(1)
            turnover = sum(
                abs(current.get(symbol, Decimal(0)) - previous.get(symbol, Decimal(0)))
                for symbol in current.keys() | previous.keys()
            )
            period_returns.append(float(net_return))
            rows.append(
                {
                    "as_of": as_of,
                    "execution_date": execution_date,
                    "exit_date": exit_date_value,
                    "gross_return": float(gross_return),
                    "net_return": float(net_return),
                    "turnover": float(turnover),
                    "cost": float(cost),
                    "equity": float(equity),
                    "terminal_cost": 0.0,
                }
            )
            previous = {
                symbol: current[symbol] * (Decimal(1) + returns[symbol]) / gross_factor
                for symbol in current
                if current[symbol] * (Decimal(1) + returns[symbol]) > 0
            }
            previous_exit_date = exit_date_value
            last_period_start_equity = start_equity
        if previous_exit_date is None:
            raise ValueError("diagnostic holding periods are empty")
        terminal_date = previous_exit_date
        terminal_cost = _target_change_cost(
            previous,
            {},
            equity=equity,
            date=terminal_date,
            multiplier=multiplier,
            costs=costs,
        )
        if terminal_cost >= equity:
            raise ValueError("diagnostic terminal costs exhaust equity")
        equity -= terminal_cost
    rows[-1]["terminal_cost"] = float(terminal_cost)
    rows[-1]["equity"] = float(equity)
    period_returns[-1] = float(equity / last_period_start_equity - Decimal(1))
    rows[-1]["net_return"] = period_returns[-1]
    nav = pl.DataFrame(rows)
    mean = sum(period_returns) / len(period_returns)
    standard_deviation = _sample_std(period_returns)
    peak = float(initial_cash)
    max_drawdown = 0.0
    for value in nav.get_column("equity"):
        peak = max(peak, float(value))
        max_drawdown = min(max_drawdown, float(value) / peak - 1.0)
    return nav, {
        "total_return": float(equity / initial_cash - Decimal(1)),
        "sharpe": mean / standard_deviation * math.sqrt(annualization_periods)
        if standard_deviation > 0
        else 0.0,
        "max_drawdown": max_drawdown,
        "average_turnover": cast(float, nav.get_column("turnover").mean()),
    }


def _target_change_cost(
    previous: Mapping[str, Decimal],
    current: Mapping[str, Decimal],
    *,
    equity: Decimal,
    date: dt.date,
    multiplier: Decimal,
    costs: tuple[AShareCostPeriod, ...],
) -> Decimal:
    matches = tuple(
        period
        for period in costs
        if period.effective_from <= date
        and (period.effective_to is None or date <= period.effective_to)
    )
    if len(matches) != 1:
        raise ValueError("diagnostic cost period missing")
    period = matches[0]
    total = Decimal(0)
    for symbol in current.keys() | previous.keys():
        delta = current.get(symbol, Decimal(0)) - previous.get(symbol, Decimal(0))
        if not delta:
            continue
        notional = abs(delta) * equity
        total += max(
            notional * period.commission_rate * multiplier,
            period.commission_min * multiplier,
        )
        total += notional * (period.transfer_fee + period.slippage * multiplier)
        if delta < 0:
            total += notional * period.stamp_tax_sell
    return total


def _sample_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


__all__ = [
    "build_diagnostic_factor_targets",
    "evaluate_factor_period",
    "evaluate_factor_redundancy",
    "newey_west_t_statistic",
    "simulate_diagnostic_factor_portfolio",
]
