"""Leakage-safe LightGBM combination for the frozen M2 classic factors."""

from __future__ import annotations

import datetime as dt
import importlib
import math
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import cast

import polars as pl

from quant.research.classic_factor_composite import (
    build_volatility_controlled_composite_targets,
)
from quant.research.classic_factor_evaluation import (
    evaluate_factor_period,
    simulate_diagnostic_factor_portfolio,
)
from quant.research.lightweight_run import ResearchFoldV1
from quant.research.m3.contracts import AShareCostPeriod

MODEL_FEATURES: tuple[str, ...] = (
    "alpha158_std20",
    "alpha158_roc20",
    "alpha158_rsv20",
    "alpha158_corr20",
    "alpha158_wvma20",
)
MODEL_SCORE = "classic_factor_lightgbm_score"


@dataclass(frozen=True)
class ClassicFactorLightgbmSpec:
    """Frozen CPU-bounded LightGBM parameters for the M2 experiment."""

    objective: str
    metric: str
    device_type: str
    learning_rate: float
    num_leaves: int
    max_depth: int
    feature_fraction: float
    bagging_fraction: float
    bagging_freq: int
    num_boost_round: int
    early_stopping_rounds: int
    seed: int
    num_threads: int

    def __post_init__(self) -> None:
        if (
            self.objective != "regression"
            or self.metric != "l2"
            or self.device_type != "cpu"
            or not math.isfinite(self.learning_rate)
            or not 0 < self.learning_rate <= 0.1
            or type(self.num_leaves) is not int
            or not 2 <= self.num_leaves <= 64
            or type(self.max_depth) is not int
            or self.max_depth < -1
            or not 0 < self.feature_fraction <= 1
            or not 0 < self.bagging_fraction <= 1
            or type(self.bagging_freq) is not int
            or self.bagging_freq < 0
            or type(self.num_boost_round) is not int
            or self.num_boost_round <= 0
            or type(self.early_stopping_rounds) is not int
            or not 0 < self.early_stopping_rounds < self.num_boost_round
            or type(self.seed) is not int
            or self.seed < 0
            or type(self.num_threads) is not int
            or not 1 <= self.num_threads <= 4
        ):
            raise ValueError("invalid classic-factor LightGBM spec")

    def parameters(self) -> dict[str, object]:
        """Return deterministic native-LightGBM parameters."""
        return {
            "objective": self.objective,
            "metric": self.metric,
            "device_type": self.device_type,
            "learning_rate": self.learning_rate,
            "num_leaves": self.num_leaves,
            "max_depth": self.max_depth,
            "feature_fraction": self.feature_fraction,
            "bagging_fraction": self.bagging_fraction,
            "bagging_freq": self.bagging_freq,
            "seed": self.seed,
            "data_random_seed": self.seed,
            "feature_fraction_seed": self.seed,
            "bagging_seed": self.seed,
            "deterministic": True,
            "force_col_wise": True,
            "num_threads": self.num_threads,
            "verbosity": -1,
        }


def build_cross_sectional_rank_features(
    panel: pl.DataFrame,
    *,
    features: tuple[str, ...] = MODEL_FEATURES,
) -> pl.DataFrame:
    """Add centered daily percentile ranks without imputing missing values."""
    if (
        not isinstance(panel, pl.DataFrame)
        or panel.is_empty()
        or type(features) is not tuple
        or not features
        or len(features) != len(set(features))
        or any(name not in panel.columns for name in features)
        or "trade_date" not in panel.columns
        or "symbol" not in panel.columns
    ):
        raise ValueError("invalid classic-factor model panel")
    expressions: list[pl.Expr] = []
    for feature in features:
        finite = pl.col(feature).is_not_null() & pl.col(feature).is_finite()
        count = finite.cast(pl.UInt32).sum().over("trade_date")
        rank = (
            pl.when(finite)
            .then(pl.col(feature))
            .otherwise(None)
            .rank("average")
            .over("trade_date")
        )
        expressions.append(
            pl.when(finite & (count > 0))
            .then(rank / count - 0.5)
            .otherwise(None)
            .alias(_rank_name(feature))
        )
    return panel.with_columns(*expressions).sort("trade_date", "symbol")


def fit_predict_lightgbm_fold(
    panel: pl.DataFrame,
    *,
    fold: ResearchFoldV1,
    spec: ClassicFactorLightgbmSpec,
    minimum_symbols: int,
) -> tuple[pl.DataFrame, dict[str, object], bytes]:
    """Fit on train, early-stop on validation, then predict validation/test once."""
    if (
        not isinstance(panel, pl.DataFrame)
        or panel.is_empty()
        or type(fold) is not ResearchFoldV1
        or type(spec) is not ClassicFactorLightgbmSpec
        or type(minimum_symbols) is not int
        or minimum_symbols < 2
    ):
        raise ValueError("invalid classic-factor model fold")
    ranked = build_cross_sectional_rank_features(panel)
    rank_features = tuple(_rank_name(name) for name in MODEL_FEATURES)
    required = (*rank_features, "label_20", "exit_date_20")
    if any(name not in ranked.columns for name in required):
        raise ValueError("classic-factor model columns are missing")
    complete_features = pl.all_horizontal(
        *[
            pl.col(name).is_not_null() & pl.col(name).is_finite()
            for name in rank_features
        ]
    )
    train = _training_slice(
        ranked,
        start=fold.train_start,
        end=fold.train_end,
        complete_features=complete_features,
    )
    validation = _training_slice(
        ranked,
        start=fold.validation_start,
        end=fold.validation_end,
        complete_features=complete_features,
    )
    test = ranked.filter(
        pl.col("trade_date").is_between(
            fold.test_start, fold.test_end, closed="both"
        )
        & (pl.col("exit_date_20") <= fold.test_end)
        & complete_features
    ).sort("trade_date", "symbol")
    if (
        train.is_empty()
        or validation.is_empty()
        or test.is_empty()
        or train.get_column("trade_date").n_unique() < 2
        or validation.get_column("trade_date").n_unique() < 2
        or test.get_column("trade_date").n_unique() < 2
    ):
        raise ValueError("classic-factor model fold is empty")
    for frame in (train, validation, test):
        minimum = cast(int, frame.group_by("trade_date").len()["len"].min())
        if minimum < minimum_symbols:
            raise ValueError("classic-factor model daily coverage is insufficient")

    lightgbm = importlib.import_module("lightgbm")
    train_set = lightgbm.Dataset(
        train.select(rank_features).to_numpy(),
        label=train.get_column("label_20").to_numpy(),
        feature_name=list(rank_features),
        free_raw_data=False,
    )
    validation_set = lightgbm.Dataset(
        validation.select(rank_features).to_numpy(),
        label=validation.get_column("label_20").to_numpy(),
        feature_name=list(rank_features),
        reference=train_set,
        free_raw_data=False,
    )
    booster = lightgbm.train(
        spec.parameters(),
        train_set,
        num_boost_round=spec.num_boost_round,
        valid_sets=[validation_set],
        valid_names=["validation"],
        callbacks=[
            lightgbm.early_stopping(
                spec.early_stopping_rounds,
                first_metric_only=True,
                verbose=False,
            ),
            lightgbm.log_evaluation(0),
        ],
    )
    best_iteration = int(booster.best_iteration)
    if not 1 <= best_iteration <= spec.num_boost_round:
        raise ValueError("LightGBM did not select a valid iteration")
    prediction_frames: list[pl.DataFrame] = []
    for period, frame in (("validation", validation), ("test", test)):
        predictions = booster.predict(
            frame.select(rank_features).to_numpy(), num_iteration=best_iteration
        )
        prediction_frames.append(
            frame.select(
                "trade_date",
                "symbol",
                "execution_date_20",
                "exit_date_20",
                "label_1",
                "label_5",
                "label_20",
            ).with_columns(
                pl.Series(MODEL_SCORE, predictions, dtype=pl.Float64),
                pl.lit(fold.fold).alias("fold"),
                pl.lit(period).alias("period"),
            )
        )
    importance_gain = booster.feature_importance(
        importance_type="gain", iteration=best_iteration
    )
    importance_split = booster.feature_importance(
        importance_type="split", iteration=best_iteration
    )
    metadata: dict[str, object] = {
        "fold": fold.fold,
        "best_iteration": best_iteration,
        "train_rows": train.height,
        "validation_rows": validation.height,
        "test_rows": test.height,
        "feature_importance_gain": {
            name: float(value) for name, value in zip(MODEL_FEATURES, importance_gain)
        },
        "feature_importance_split": {
            name: int(value) for name, value in zip(MODEL_FEATURES, importance_split)
        },
    }
    model_bytes = booster.model_to_string(
        num_iteration=best_iteration
    ).encode("utf-8")
    return (
        pl.concat(prediction_frames).sort("period", "trade_date", "symbol"),
        metadata,
        model_bytes,
    )


def evaluate_lightgbm_walk_forward(
    *,
    panel: pl.DataFrame,
    folds: tuple[ResearchFoldV1, ...],
    spec: ClassicFactorLightgbmSpec,
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
    risk_prices: pl.DataFrame,
    risk_symbol: str,
) -> tuple[dict[str, pl.DataFrame], dict[int, bytes]]:
    """Run the frozen walk-forward model and diagnostic portfolio."""
    prediction_frames: list[pl.DataFrame] = []
    daily_frames: list[pl.DataFrame] = []
    group_frames: list[pl.DataFrame] = []
    metadata_rows: list[dict[str, object]] = []
    metric_rows: list[dict[str, object]] = []
    target_frames: list[pl.DataFrame] = []
    period_frames: list[pl.DataFrame] = []
    nav_frames: list[pl.DataFrame] = []
    models: dict[int, bytes] = {}
    for fold in folds:
        predictions, metadata, model_bytes = fit_predict_lightgbm_fold(
            panel,
            fold=fold,
            spec=spec,
            minimum_symbols=minimum_symbols,
        )
        models[fold.fold] = model_bytes
        prediction_frames.append(predictions)
        metadata_rows.append(metadata)
        scored = panel.join(
            predictions.filter(pl.col("period") == "test").select(
                "trade_date", "symbol", MODEL_SCORE
            ),
            on=["trade_date", "symbol"],
            how="left",
            validate="1:1",
        )
        validation_scored = panel.join(
            predictions.filter(pl.col("period") == "validation").select(
                "trade_date", "symbol", MODEL_SCORE
            ),
            on=["trade_date", "symbol"],
            how="left",
            validate="1:1",
        )
        validation_daily, validation_groups, validation_metrics = (
            evaluate_factor_period(
                validation_scored,
                factor=MODEL_SCORE,
                horizon=20,
                start_date=fold.validation_start,
                end_date=fold.validation_end,
                minimum_symbols=minimum_symbols,
                groups=groups,
            )
        )
        daily_frames.append(
            _identity(validation_daily, fold.fold, "validation", 20)
        )
        group_frames.append(
            _identity(validation_groups, fold.fold, "validation", 20)
        )
        test20_metrics: Mapping[str, float | int] | None = None
        for horizon in (1, 5, 20):
            daily, grouped, metrics = evaluate_factor_period(
                scored,
                factor=MODEL_SCORE,
                horizon=horizon,
                start_date=fold.test_start,
                end_date=fold.test_end,
                minimum_symbols=minimum_symbols,
                groups=groups,
            )
            daily_frames.append(_identity(daily, fold.fold, "test", horizon))
            group_frames.append(_identity(grouped, fold.fold, "test", horizon))
            if horizon == 20:
                test20_metrics = metrics
        if test20_metrics is None:
            raise ValueError("model test horizon 20 is missing")
        targets, periods = build_volatility_controlled_composite_targets(
            scored,
            factor=MODEL_SCORE,
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
                    pl.lit(MODEL_SCORE).alias("factor"),
                    pl.lit(fold.fold).alias("fold"),
                    pl.lit(float(multiplier)).alias("cost_multiplier"),
                )
            )
            metric_rows.append(
                {
                    "factor": MODEL_SCORE,
                    "fold": fold.fold,
                    "direction": 1,
                    "cost_multiplier": float(multiplier),
                    "validation_rank_ic": float(
                        validation_metrics["rank_ic_mean"]
                    ),
                    "test_rank_ic": float(test20_metrics["rank_ic_mean"]),
                    "test_ic_dates": int(test20_metrics["dates"]),
                    "mean_invested_weight": cast(
                        float, periods.get_column("invested_weight").mean()
                    ),
                    "cash_period_fraction": cast(
                        float,
                        periods.select(
                            (pl.col("invested_weight") == 0).mean()
                        ).item(),
                    ),
                    **portfolio_metrics,
                }
            )
    return (
        {
            "predictions": pl.concat(prediction_frames).sort(
                "fold", "period", "trade_date", "symbol"
            ),
            "model_metadata": pl.DataFrame(metadata_rows).sort("fold"),
            "daily_ic": pl.concat(daily_frames).sort(
                "fold", "period", "horizon", "trade_date"
            ),
            "group_returns": pl.concat(group_frames).sort(
                "fold", "period", "horizon", "trade_date", "group"
            ),
            "fold_metrics": pl.DataFrame(metric_rows).sort(
                "fold", "cost_multiplier"
            ),
            "targets": pl.concat(target_frames).sort("as_of", "strategy", "symbol"),
            "periods": pl.concat(period_frames).sort("fold", "as_of"),
            "portfolio_nav": pl.concat(nav_frames).sort(
                "fold", "cost_multiplier", "as_of"
            ),
        },
        models,
    )


def _training_slice(
    panel: pl.DataFrame,
    *,
    start: dt.date,
    end: dt.date,
    complete_features: pl.Expr,
) -> pl.DataFrame:
    return panel.filter(
        pl.col("trade_date").is_between(start, end, closed="both")
        & (pl.col("exit_date_20") <= end)
        & complete_features
        & pl.col("label_20").is_not_null()
        & pl.col("label_20").is_finite()
    ).sort("trade_date", "symbol")


def _rank_name(feature: str) -> str:
    return f"{feature}_rank"


def _identity(
    frame: pl.DataFrame, fold: int, period: str, horizon: int
) -> pl.DataFrame:
    return frame.with_columns(
        pl.lit(fold).alias("fold"),
        pl.lit(period).alias("period"),
        pl.lit(MODEL_SCORE).alias("factor"),
        pl.lit(horizon).alias("horizon"),
    )


__all__ = [
    "MODEL_FEATURES",
    "MODEL_SCORE",
    "ClassicFactorLightgbmSpec",
    "build_cross_sectional_rank_features",
    "evaluate_lightgbm_walk_forward",
    "fit_predict_lightgbm_fold",
]
