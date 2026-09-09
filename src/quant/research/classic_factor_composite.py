"""Pre-registered equal-rank composite research for the M2 classic factors."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import cast

import polars as pl

from quant.portfolio import scale_target_weights_to_volatility
from quant.research.classic_factor_evaluation import (
    build_diagnostic_factor_targets,
    evaluate_factor_period,
    simulate_diagnostic_factor_portfolio,
)
from quant.research.lightweight_run import ResearchFoldV1
from quant.research.m3.contracts import AShareCostPeriod

COMPOSITE_COMPONENTS = (
    "alpha158_std20",
    "alpha158_roc20",
    "alpha158_rsv20",
)
COMPOSITE_NAME = "alpha158_std_roc_rsv_equal_rank"


def build_equal_weight_zscore_composite(
    panel: pl.DataFrame, *, component_directions: tuple[tuple[str, int], ...],
    output_name: str = "equal_zscore",
) -> pl.DataFrame:
    """Standardize complete cases within each signal-date cross-section."""
    if not component_directions or any(d not in {-1, 1} for _, d in component_directions):
        raise ValueError("Invalid z-score component directions")
    if len({name for name, _ in component_directions}) != len(component_directions):
        raise ValueError("Duplicate z-score components")
    complete = panel.filter(pl.all_horizontal([
        pl.col(name).is_not_null() & pl.col(name).is_finite()
        for name, _ in component_directions
    ]))
    scores = []
    for name, direction in component_directions:
        sigma = pl.col(name).std(ddof=0).over("trade_date")
        scores.append(pl.when(sigma > 0).then(
            direction * (pl.col(name) - pl.col(name).mean().over("trade_date")) / sigma
        ).otherwise(0.0))
    return complete.with_columns((pl.sum_horizontal(scores) / len(scores)).alias(output_name))


def build_monthly_zscore_targets(
    panel: pl.DataFrame, *, sessions: tuple[dt.date, ...], start: dt.date,
    end: dt.date, top_k: int, strategy_name: str,
) -> pl.DataFrame:
    """Take Top-K at the prior close for initial deployment and month changes."""
    signals = [(day, following) for day, following in zip(sessions, sessions[1:])
               if start <= following <= end
               and (day < start or day.month != following.month)]
    rows: list[dict[str, object]] = []
    for as_of, execution_date in signals:
        selected = panel.filter(pl.col("trade_date") == as_of).sort(
            "equal_zscore", "symbol", descending=[True, False],
        ).head(top_k)
        if selected.height != top_k:
            raise ValueError(f"Insufficient complete factors on {as_of}")
        rows.extend({"as_of": as_of, "execution_date": execution_date,
                     "strategy": strategy_name, "strategy_version": "v1",
                     "symbol": symbol, "weight": 1.0 / top_k}
                    for symbol in selected.get_column("symbol"))
    if not rows:
        raise ValueError("No monthly signals in the requested window")
    return pl.DataFrame(rows).sort("execution_date", "symbol")


def infer_validation_component_directions(
    panel: pl.DataFrame,
    *,
    components: tuple[str, ...],
    validation_start: dt.date,
    validation_end: dt.date,
    minimum_symbols: int,
    groups: int,
) -> tuple[tuple[str, int], ...]:
    """Choose each component sign from validation RankIC only."""
    if components != COMPOSITE_COMPONENTS:
        raise ValueError("invalid composite components")
    directions: list[tuple[str, int]] = []
    for component in components:
        _, _, metrics = evaluate_factor_period(
            panel,
            factor=component,
            horizon=20,
            start_date=validation_start,
            end_date=validation_end,
            minimum_symbols=minimum_symbols,
            groups=groups,
        )
        directions.append(
            (component, 1 if float(metrics["rank_ic_mean"]) >= 0 else -1)
        )
    return tuple(directions)


def build_equal_weight_rank_composite(
    panel: pl.DataFrame,
    *,
    component_directions: tuple[tuple[str, int], ...],
    output_name: str = COMPOSITE_NAME,
) -> pl.DataFrame:
    """Add the mean daily percentile rank of the three directed components."""
    if (
        not isinstance(panel, pl.DataFrame)
        or panel.is_empty()
        or tuple(name for name, _ in component_directions) != COMPOSITE_COMPONENTS
        or any(direction not in {-1, 1} for _, direction in component_directions)
        or type(output_name) is not str
        or not output_name
        or output_name in panel.columns
    ):
        raise ValueError("invalid equal-rank composite request")
    valid = pl.all_horizontal(
        *[
            pl.col(name).is_not_null() & pl.col(name).is_finite()
            for name, _ in component_directions
        ]
    )
    count_name = "__composite_valid_count"
    rank_names: list[str] = []
    expressions: list[pl.Expr] = []
    for index, (name, direction) in enumerate(component_directions):
        rank_name = f"__composite_rank_{index}"
        rank_names.append(rank_name)
        expressions.append(
            pl.when(valid)
            .then(pl.col(name) * direction)
            .otherwise(None)
            .rank("average")
            .over("trade_date")
            .alias(rank_name)
        )
    ranked = panel.with_columns(
        valid.cast(pl.Int64).sum().over("trade_date").alias(count_name),
        *expressions,
    )
    score = pl.sum_horizontal(
        *[pl.col(name) / pl.col(count_name) for name in rank_names]
    ) / len(rank_names)
    return ranked.with_columns(
        pl.when(pl.col(count_name) > 0).then(score).otherwise(None).alias(output_name)
    ).drop(count_name, *rank_names)


def build_volatility_controlled_composite_targets(
    panel: pl.DataFrame,
    *,
    factor: str,
    fold: int,
    test_start: dt.date,
    test_end: dt.date,
    top_k: int,
    rebalance_every_sessions: int,
    minimum_symbols: int,
    strategy_name: str,
    strategy_version: str,
    lookback_observations: int,
    annualized_target_volatility: float,
    annualization_sessions: int,
    risk_prices: pl.DataFrame | None = None,
    risk_symbol: str | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Build Top-K targets, then apply the existing unlevered risk control."""
    targets, periods = build_diagnostic_factor_targets(
        panel,
        factor=factor,
        direction=1,
        fold=fold,
        test_start=test_start,
        test_end=test_end,
        top_k=top_k,
        rebalance_every_sessions=rebalance_every_sessions,
        minimum_symbols=minimum_symbols,
        strategy_name=strategy_name,
        strategy_version=strategy_version,
    )
    if (risk_prices is None) != (risk_symbol is None):
        raise ValueError("risk prices and symbol must be provided together")
    prices = (
        panel.select(
            "symbol",
            "trade_date",
            (pl.col("close") * pl.col("adj_factor")).alias("adjusted_close"),
            pl.lit("CUMULATIVE_FACTOR").alias("adjustment_method"),
            "source",
        ).sort("symbol", "trade_date")
        if risk_prices is None
        else risk_prices
    )
    scaled_frames: list[pl.DataFrame] = []
    period_rows: list[dict[str, object]] = []
    for period in periods.iter_rows(named=True):
        as_of = cast(dt.date, period["as_of"])
        current = targets.filter(pl.col("as_of") == as_of)
        current_symbols = (
            current.get_column("symbol").implode()
            if risk_symbol is None
            else pl.Series("symbol", [risk_symbol]).implode()
        )
        current_prices = (
            prices.filter(
                (pl.col("trade_date") <= as_of)
                & pl.col("symbol").is_in(current_symbols)
            )
            .group_by("symbol", maintain_order=True)
            .tail(lookback_observations + 1)
            .sort("symbol", "trade_date")
        )
        risk_targets = (
            current.select(
                "as_of", "strategy", "strategy_version", "symbol", "weight"
            )
            if risk_symbol is None
            else pl.DataFrame(
                {
                    "as_of": [as_of],
                    "strategy": ["benchmark_market_risk"],
                    "strategy_version": ["v1"],
                    "symbol": [risk_symbol],
                    "weight": [1.0],
                }
            )
        )
        scaled = scale_target_weights_to_volatility(
            targets=risk_targets,
            prices=current_prices,
            lookback_observations=lookback_observations,
            annualized_target_volatility=annualized_target_volatility,
            annualization_sessions=annualization_sessions,
        )
        if risk_symbol is None:
            controlled = (
                current.rename({"weight": "base_weight"})
                .join(
                    scaled.select(
                        "as_of",
                        "strategy",
                        "symbol",
                        pl.col("weight").alias("controlled_weight"),
                    ),
                    on=["as_of", "strategy", "symbol"],
                    how="left",
                    validate="1:1",
                )
                .with_columns(pl.col("controlled_weight").alias("weight"))
                .with_columns(
                    (pl.col("weight").sum().over("as_of")).alias("risk_scale")
                )
                .drop("controlled_weight")
            )
        else:
            risk_scale = cast(float, scaled.item(0, "weight"))
            controlled = current.rename({"weight": "base_weight"}).with_columns(
                (pl.col("base_weight") * risk_scale).alias("weight"),
                pl.lit(risk_scale).alias("risk_scale"),
            )
        scaled_frames.append(controlled)
        labels = panel.filter(
            (pl.col("trade_date") == as_of)
            & pl.col("symbol").is_in(controlled.get_column("symbol").implode())
        ).select("symbol", "label_20")
        weighted = controlled.select("symbol", "weight").join(
            labels, on="symbol", how="left", validate="1:1"
        )
        if weighted.get_column("label_20").null_count() or weighted.height != top_k:
            raise ValueError("controlled target labels are incomplete")
        period_rows.append(
            {
                **period,
                "gross_return_unscaled": period["gross_return"],
                "gross_return": cast(
                    float,
                    weighted.select((pl.col("weight") * pl.col("label_20")).sum()).item(),
                ),
                "invested_weight": cast(float, controlled.get_column("weight").sum()),
            }
        )
    result_targets = pl.concat(scaled_frames).sort("as_of", "strategy", "symbol")
    return result_targets, pl.DataFrame(period_rows).sort("as_of")


def evaluate_composite_walk_forward(
    *,
    panel: pl.DataFrame,
    components: tuple[str, ...],
    composite_name: str,
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
    lookback_observations: int,
    annualized_target_volatility: float,
    annualization_sessions: int,
    risk_prices: pl.DataFrame | None = None,
    risk_symbol: str | None = None,
) -> dict[str, pl.DataFrame]:
    """Evaluate the frozen composite without reading test labels during fitting."""
    direction_rows: list[dict[str, object]] = []
    daily_frames: list[pl.DataFrame] = []
    group_frames: list[pl.DataFrame] = []
    metric_rows: list[dict[str, object]] = []
    target_frames: list[pl.DataFrame] = []
    period_frames: list[pl.DataFrame] = []
    nav_frames: list[pl.DataFrame] = []
    for fold in folds:
        directions = infer_validation_component_directions(
            panel,
            components=components,
            validation_start=fold.validation_start,
            validation_end=fold.validation_end,
            minimum_symbols=minimum_symbols,
            groups=groups,
        )
        direction_rows.extend(
            {"fold": fold.fold, "component": name, "direction": direction}
            for name, direction in directions
        )
        scored = build_equal_weight_rank_composite(
            panel, component_directions=directions, output_name=composite_name
        )
        validation_daily, validation_groups, validation_metrics = evaluate_factor_period(
            scored,
            factor=composite_name,
            horizon=20,
            start_date=fold.validation_start,
            end_date=fold.validation_end,
            minimum_symbols=minimum_symbols,
            groups=groups,
        )
        daily_frames.append(
            _with_identity(
                validation_daily,
                fold=fold.fold,
                period="validation",
                factor=composite_name,
                horizon=20,
            )
        )
        group_frames.append(
            _with_identity(
                validation_groups,
                fold=fold.fold,
                period="validation",
                factor=composite_name,
                horizon=20,
            )
        )
        test20_metrics: dict[str, float | int] | None = None
        for horizon in horizons:
            test_daily, test_groups, test_metrics = evaluate_factor_period(
                scored,
                factor=composite_name,
                horizon=horizon,
                start_date=fold.test_start,
                end_date=fold.test_end,
                minimum_symbols=minimum_symbols,
                groups=groups,
            )
            daily_frames.append(
                _with_identity(
                    test_daily,
                    fold=fold.fold,
                    period="test",
                    factor=composite_name,
                    horizon=horizon,
                )
            )
            group_frames.append(
                _with_identity(
                    test_groups,
                    fold=fold.fold,
                    period="test",
                    factor=composite_name,
                    horizon=horizon,
                )
            )
            if horizon == 20:
                test20_metrics = test_metrics
        if test20_metrics is None:
            raise ValueError("test horizon 20 is missing")
        targets, periods = build_volatility_controlled_composite_targets(
            scored,
            factor=composite_name,
            fold=fold.fold,
            test_start=fold.test_start,
            test_end=fold.test_end,
            top_k=top_k,
            rebalance_every_sessions=rebalance_every,
            minimum_symbols=minimum_symbols,
            strategy_name=strategy_name,
            strategy_version=strategy_version,
            lookback_observations=lookback_observations,
            annualized_target_volatility=annualized_target_volatility,
            annualization_sessions=annualization_sessions,
            risk_prices=risk_prices,
            risk_symbol=risk_symbol,
        )
        target_frames.append(targets)
        period_frames.append(periods.with_columns(pl.lit(fold.fold).alias("fold")))
        holding_outcomes = scored.select(
            pl.col("trade_date").alias("as_of"),
            "symbol",
            pl.col("label_20").alias("holding_return"),
        )
        for multiplier in cost_multipliers:
            nav, portfolio_metrics = simulate_diagnostic_factor_portfolio(
                targets=targets,
                periods=periods,
                holding_outcomes=holding_outcomes,
                costs=costs,
                multiplier=multiplier,
                initial_cash=initial_cash,
            )
            nav_frames.append(
                nav.with_columns(
                    pl.lit(composite_name).alias("factor"),
                    pl.lit(fold.fold).alias("fold"),
                    pl.lit(float(multiplier)).alias("cost_multiplier"),
                )
            )
            metric_rows.append(
                {
                    "factor": composite_name,
                    "fold": fold.fold,
                    "direction": 1,
                    "cost_multiplier": float(multiplier),
                    "validation_rank_ic": float(validation_metrics["rank_ic_mean"]),
                    "test_rank_ic": float(test20_metrics["rank_ic_mean"]),
                    "test_ic_dates": int(test20_metrics["dates"]),
                    "mean_invested_weight": cast(
                        float, periods.get_column("invested_weight").mean()
                    ),
                    "cash_period_fraction": cast(
                        float,
                        periods.select((pl.col("invested_weight") == 0).mean()).item(),
                    ),
                    **portfolio_metrics,
                }
            )
    return {
        "component_directions": pl.DataFrame(direction_rows).sort("fold", "component"),
        "daily_ic": pl.concat(daily_frames).sort(
            "fold", "period", "factor", "horizon", "trade_date"
        ),
        "group_returns": pl.concat(group_frames).sort(
            "fold", "period", "factor", "horizon", "trade_date", "group"
        ),
        "fold_metrics": pl.DataFrame(metric_rows).sort(
            "factor", "fold", "cost_multiplier"
        ),
        "targets": pl.concat(target_frames).sort("as_of", "strategy", "symbol"),
        "periods": pl.concat(period_frames).sort("fold", "as_of"),
        "portfolio_nav": pl.concat(nav_frames).sort(
            "factor", "fold", "cost_multiplier", "as_of"
        ),
    }


def _with_identity(
    frame: pl.DataFrame,
    *,
    fold: int,
    period: str,
    factor: str,
    horizon: int,
) -> pl.DataFrame:
    return frame.with_columns(
        pl.lit(fold).alias("fold"),
        pl.lit(period).alias("period"),
        pl.lit(factor).alias("factor"),
        pl.lit(horizon).alias("horizon"),
        pl.lit(1).alias("direction"),
    )


__all__ = [
    "COMPOSITE_COMPONENTS",
    "COMPOSITE_NAME",
    "build_equal_weight_rank_composite",
    "build_volatility_controlled_composite_targets",
    "evaluate_composite_walk_forward",
    "infer_validation_component_directions",
]
