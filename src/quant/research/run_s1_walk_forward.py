"""ETF 趋势策略的滚动验证、冻结测试与成本压力。"""

import argparse
import datetime as dt
import hashlib
import io
import json
import math
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Sequence, cast

import polars as pl

from quant.backtest import (
    EtfDiagnosticSimulationResult,
    EtfCostModel,
    schedule_next_trading_day,
    simulate_etf_targets_with_diagnostics,
)
from quant.factors import compute_trend_factors_from_prices
from quant.portfolio import (
    retain_ranked_target_selection,
    scale_target_weights_to_volatility,
)
from quant.research.lightweight_run import (
    LightweightResearchRunV1,
    ResearchFoldV1,
    canonical_json_bytes,
    compute_code_sha256,
    dataframe_input_digest,
    publish_lightweight_research_run,
)
from quant.strategies import (
    BreadthFilteredEtfTrendStrategy,
    EqualWeightStrategy,
    EtfTrendStrategy,
    RegimeFilteredEtfTrendStrategy,
)

_HYPOTHESIS_ID = "s1-trend-v1"
_HYPOTHESIS = (
    "Positive multi-horizon momentum and positive regression trend can select "
    "a small ETF portfolio with cost-robust out-of-sample value."
)
_STRATEGY_KIND: Literal["etf_trend"] = "etf_trend"
_CODE_PATHS = (
    "src/quant/backtest/costs.py",
    "src/quant/backtest/simulator.py",
    "src/quant/backtest/timing.py",
    "src/quant/factors/trend.py",
    "src/quant/portfolio/selection.py",
    "src/quant/research/lightweight_run.py",
    "src/quant/research/run_s1_walk_forward.py",
    "src/quant/strategies/baselines.py",
)


@dataclass(frozen=True)
class Fold:
    fold: int
    train_start: dt.date
    train_end: dt.date
    validation_start: dt.date
    validation_end: dt.date
    test_start: dt.date
    test_end: dt.date


@dataclass(frozen=True)
class Parameters:
    top_k: int
    regression_window: int


@dataclass(frozen=True)
class ResearchSpec:
    hypothesis_id: str
    hypothesis: str
    strategy_kind: Literal[
        "etf_trend", "etf_regime_trend", "etf_breadth_regime_trend"
    ]
    strategy_version: str
    conclusion: Literal["REJECTED", "RESEARCH_ONLY"]
    random_seed: int


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行 M2 ETF 规则策略 walk-forward")
    parser.add_argument(
        "--config", type=Path, default=Path("configs/research/m2_baseline.toml")
    )
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    parser.add_argument("--project-root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    project_root = args.project_root.resolve(strict=True)
    config_path = _inside(project_root, args.config)
    data_root = _inside(project_root, args.data_root)
    artifact_root = _inside(project_root, args.artifact_root, strict=False)
    config_payload = config_path.read_bytes()
    with config_path.open("rb") as stream:
        config: dict[str, Any] = tomllib.load(stream)
    walk = config["walk_forward"]
    if not walk["enabled"]:
        raise ValueError("walk_forward.enabled 必须显式为 true")
    rebalance_months = walk.get("rebalance_months", 1)
    if (
        not isinstance(rebalance_months, int)
        or isinstance(rebalance_months, bool)
        or rebalance_months <= 0
    ):
        raise ValueError("walk_forward.rebalance_months 必须是正整数")
    research = _research_spec(config)
    data_start, data_end = config["data"]["start_date"], config["data"]["end_date"]
    folds = make_folds(
        start=data_start,
        end=data_end,
        train_months=walk["train_months"],
        validation_months=walk["validation_months"],
        test_months=walk["test_months"],
        step_months=walk["step_months"],
    )
    if not folds:
        raise ValueError("历史长度不足以形成完整 walk-forward 折")
    candidates = _candidates(config)
    bars = pl.read_parquet(
        data_root / "clean" / "bar_1d" / "date=*" / "data.parquet"
    ).filter(
        pl.col("symbol").is_in(candidates)
        & pl.col("trade_date").is_between(data_start, data_end, closed="both")
        & (
            ((pl.col("trade_date") < dt.date(2026, 1, 1)) & (pl.col("source") == "akshare"))
            | ((pl.col("trade_date") >= dt.date(2026, 1, 1)) & (pl.col("source") == "baostock"))
        )
    )
    prices = pl.read_parquet(
        data_root / "clean" / "research_price_1d" / "date=*" / "data.parquet"
    ).filter(
        pl.col("symbol").is_in(candidates)
        & (pl.col("adjustment_method") == "TOTAL_RETURN_DIVIDEND")
        & pl.col("trade_date").is_between(data_start, data_end, closed="both")
    )
    calendars = pl.concat([
        pl.read_parquet(
            data_root / "clean" / "trade_calendar" / f"market={market}" / "data.parquet"
        )
        for market in ("SH", "SZ")
    ])
    instruments = pl.concat([
        pl.read_parquet(
            data_root / "clean" / "instrument" / f"market={market}" / "data.parquet"
        )
        for market in ("SH", "SZ")
    ]).filter(pl.col("symbol").is_in(candidates))
    _require_symbol_coverage(bars, candidates, "成交行情")
    _require_symbol_coverage(prices, candidates, "总回报价格")

    strategy_config = config["strategy"][research.strategy_kind]
    volatility_target = _volatility_target_spec(strategy_config)
    grid = [
        Parameters(top_k=top_k, regression_window=window)
        for top_k in walk["grid"]["top_k"]
        for window in walk["grid"]["regression_window"]
    ]
    base_costs = _costs(config, 1.0)
    initial_cash = config["backtest"]["initial_cash"]
    fold_reports: list[dict[str, object]] = []
    one_x_results: list[dict[str, float]] = []
    baseline_one_x_results: list[dict[str, float]] = []
    nav_outputs: list[pl.DataFrame] = []
    trade_outputs: list[pl.DataFrame] = []
    target_outputs: list[pl.DataFrame] = []
    target_gap_outputs: list[pl.DataFrame] = []

    for fold in folds:
        validation_scores: list[tuple[Parameters, dict[str, float]]] = []
        for params in grid:
            validation = evaluate_window(
                bars=bars,
                prices=prices,
                calendars=calendars,
                instruments=instruments,
                candidates=candidates,
                start=fold.validation_start,
                end=fold.validation_end,
                params=params,
                strategy_config=strategy_config,
                costs=base_costs,
                initial_cash=initial_cash,
                strategy_kind=research.strategy_kind,
                strategy_version=research.strategy_version,
                strategy_name=(
                    f"{research.hypothesis_id.replace('-', '_')}_fold_"
                    f"{fold.fold}_validation"
                ),
                rebalance_months=rebalance_months,
            )
            validation_scores.append((
                params,
                metrics(
                    validation.nav,
                    validation.trades,
                    initial_cash=initial_cash,
                    target_gaps=validation.target_gaps,
                ),
            ))
        chosen, chosen_validation = max(
            validation_scores,
            key=lambda item: (
                item[1]["sharpe"],
                item[1]["total_return"],
                -item[0].top_k,
                -item[0].regression_window,
            ),
        )
        pressure: list[dict[str, object]] = []
        test_one_x: dict[str, float] | None = None
        test_strategy_name = (
            f"{research.hypothesis_id.replace('-', '_')}_fold_{fold.fold}_test"
        )
        test_targets = build_window_targets(
            prices=prices,
            calendars=calendars,
            candidates=candidates,
            start=fold.test_start,
            end=fold.test_end,
            params=chosen,
            strategy_config=strategy_config,
            strategy_kind=research.strategy_kind,
            strategy_version=research.strategy_version,
            strategy_name=test_strategy_name,
            rebalance_months=rebalance_months,
        )
        target_outputs.append(test_targets.with_columns(pl.lit(fold.fold).alias("fold")))
        baseline_targets = build_equal_weight_targets(
            prices=prices,
            calendars=calendars,
            candidates=candidates,
            start=fold.test_start,
            end=fold.test_end,
            cash_buffer=config["strategy"]["equal_weight"]["cash_buffer"],
            strategy_name=f"s0_equal_fold_{fold.fold}_test",
            rebalance_months=rebalance_months,
        )
        baseline_pressure: list[dict[str, object]] = []
        baseline_one_x: dict[str, float] | None = None
        for multiplier in walk["cost_multipliers"]:
            result = simulate_window(
                bars=bars,
                prices=prices,
                instruments=instruments,
                start=fold.test_start,
                end=fold.test_end,
                targets=test_targets,
                costs=_costs(config, multiplier),
                initial_cash=initial_cash,
                strategy_name=test_strategy_name,
            )
            result_metrics = metrics(
                result.nav,
                result.trades,
                initial_cash=initial_cash,
                target_gaps=result.target_gaps,
            )
            pressure.append({"cost_multiplier": multiplier, **result_metrics})
            if multiplier == 1.0:
                test_one_x = result_metrics
            nav_outputs.append(
                result.nav.with_columns(
                    pl.lit(fold.fold).alias("fold"),
                    pl.lit(multiplier).alias("cost_multiplier"),
                )
            )
            trade_outputs.append(
                result.trades.with_columns(
                    pl.lit(fold.fold).alias("fold"),
                    pl.lit(multiplier).alias("cost_multiplier"),
                )
            )
            target_gap_outputs.append(
                result.target_gaps.with_columns(
                    pl.lit("candidate").alias("comparison"),
                    pl.lit(fold.fold).alias("fold"),
                    pl.lit(multiplier).alias("cost_multiplier"),
                )
            )
            baseline_result = simulate_window(
                bars=bars,
                prices=prices,
                instruments=instruments,
                start=fold.test_start,
                end=fold.test_end,
                targets=baseline_targets,
                costs=_costs(config, multiplier),
                initial_cash=initial_cash,
                strategy_name=f"s0_equal_fold_{fold.fold}_test",
            )
            baseline_metrics = metrics(
                baseline_result.nav,
                baseline_result.trades,
                initial_cash=initial_cash,
                target_gaps=baseline_result.target_gaps,
            )
            baseline_pressure.append({
                "cost_multiplier": multiplier,
                **baseline_metrics,
            })
            if multiplier == 1.0:
                baseline_one_x = baseline_metrics
            target_gap_outputs.append(
                baseline_result.target_gaps.with_columns(
                    pl.lit("s0_equal").alias("comparison"),
                    pl.lit(fold.fold).alias("fold"),
                    pl.lit(multiplier).alias("cost_multiplier"),
                )
            )
        if test_one_x is None:
            raise ValueError("成本压力必须包含 1.0 倍场景")
        if baseline_one_x is None:
            raise ValueError("S0 成本压力必须包含 1.0 倍场景")
        one_x_results.append(test_one_x)
        baseline_one_x_results.append(baseline_one_x)
        fold_reports.append({
            "fold": fold.fold,
            "train": [fold.train_start.isoformat(), fold.train_end.isoformat()],
            "validation": [
                fold.validation_start.isoformat(), fold.validation_end.isoformat()
            ],
            "test": [fold.test_start.isoformat(), fold.test_end.isoformat()],
            "selected_parameters": {
                "top_k": chosen.top_k,
                "regression_window": chosen.regression_window,
            },
            "selected_validation_metrics": chosen_validation,
            "test_1x_metrics": test_one_x,
            "validation_to_test_return_delta": (
                test_one_x["total_return"] - chosen_validation["total_return"]
            ),
            "validation_grid": [
                {
                    "top_k": params.top_k,
                    "regression_window": params.regression_window,
                    **score,
                }
                for params, score in validation_scores
            ],
            "test_cost_pressure": pressure,
            "s0_equal_test_1x_metrics": baseline_one_x,
            "s0_equal_test_cost_pressure": baseline_pressure,
        })

    compounded_return = math.prod(
        1 + result["total_return"] for result in one_x_results
    ) - 1
    baseline_compounded_return = math.prod(
        1 + result["total_return"] for result in baseline_one_x_results
    ) - 1
    caveats: tuple[str, ...] = (
        "参数仅在每折验证集选择，测试集不参与选择",
        "规则策略的训练段仅用于因子预热，不拟合模型参数",
        "ETF_POOL_M2_V1 于 2026-07-12 才冻结，历史回看仍有候选池后见偏差",
        "ETF 涨跌停状态仍依赖现有输入覆盖；缺失时不得据此晋级 PAPER",
        "M2 兼容模拟器的目标缺口只覆盖整手、现金和缺开盘价；晋级 PAPER 前仍须用统一日频或 formal 执行模拟补齐停牌、涨跌停与 T+1 拒单",
        "成本参数尚未用券商账单校准",
    )
    if volatility_target is not None:
        lookback, target_volatility, annualization_sessions = volatility_target
        caveats += (
            "波动率目标仅使用信号日可见的总回报价格，"
            f"回看 {lookback} 个共同收益观测、年化 {annualization_sessions} 日、"
            f"目标 {target_volatility:.2%}，只降风险且不加杠杆",
        )
    aggregate = {
        "compounded_test_return": compounded_return,
        "positive_folds": sum(result["total_return"] > 0 for result in one_x_results),
        "fold_count": len(one_x_results),
        "worst_fold_return": min(result["total_return"] for result in one_x_results),
        "worst_fold_max_drawdown": min(result["max_drawdown"] for result in one_x_results),
    }
    target_gaps = pl.concat(target_gap_outputs, how="vertical_relaxed").sort(
        "comparison", "fold", "cost_multiplier", "date", "symbol"
    )
    unresolved_gaps = target_gaps.filter(pl.col("gap_reason") != "NONE")
    gap_reason_counts = {
        reason: count
        for reason, count in unresolved_gaps.group_by("gap_reason").len().sort(
            "gap_reason"
        ).iter_rows()
    }
    report = {
        "config": config_path.relative_to(project_root).as_posix(),
        "hypothesis_id": research.hypothesis_id,
        "hypothesis": research.hypothesis,
        "selection_metric": walk["selection_metric"],
        "rebalance_months": rebalance_months,
        "volatility_target": (
            None
            if volatility_target is None
            else {
                "lookback_observations": volatility_target[0],
                "annualized_volatility": volatility_target[1],
                "annualization_sessions": volatility_target[2],
                "leverage_allowed": False,
            }
        ),
        "folds": fold_reports,
        "aggregate_1x": {
            **aggregate,
            "selected_parameters": [
                fold["selected_parameters"] for fold in fold_reports
            ],
        },
        "s0_equal_aggregate_1x": {
            "compounded_test_return": baseline_compounded_return,
            "positive_folds": sum(
                result["total_return"] > 0 for result in baseline_one_x_results
            ),
            "fold_count": len(baseline_one_x_results),
            "worst_fold_return": min(
                result["total_return"] for result in baseline_one_x_results
            ),
            "worst_fold_max_drawdown": min(
                result["max_drawdown"] for result in baseline_one_x_results
            ),
        },
        "caveats": list(caveats),
        "execution_diagnostics": {
            "trade_activity": "reported",
            "target_gaps": "test_target_gaps.parquet",
            "unresolved_gap_rows": unresolved_gaps.height,
            "gap_reason_counts": gap_reason_counts,
            "market_rule_rejections": (
                "available_in_authoritative_daily_simulator_and_formal_execution"
            ),
        },
    }
    nav = pl.concat(nav_outputs, how="vertical_relaxed").sort(
        "fold", "cost_multiplier", "date"
    )
    trades = pl.concat(trade_outputs, how="vertical_relaxed").sort(
        "fold", "cost_multiplier", "date", "symbol", "side"
    )
    targets = pl.concat(target_outputs, how="vertical_relaxed").sort(
        "fold", "execution_date", "symbol"
    )
    output_payloads = {
        "report.json": canonical_json_bytes(report),
        "test_nav.parquet": _parquet_bytes(nav),
        "test_targets.parquet": _parquet_bytes(targets),
        "test_target_gaps.parquet": _parquet_bytes(target_gaps),
        "test_trades.parquet": _parquet_bytes(trades),
    }
    universe = config["universe"]
    run = LightweightResearchRunV1(
        schema_version="lightweight-research-run-v1",
        run_id="",
        hypothesis_id=research.hypothesis_id,
        hypothesis=research.hypothesis,
        strategy_name=research.strategy_kind,
        strategy_version=research.strategy_version,
        conclusion=research.conclusion,
        random_seed=research.random_seed,
        config_relative_path=config_path.relative_to(project_root).as_posix(),
        config_sha256=hashlib.sha256(config_payload).hexdigest(),
        code_sha256=compute_code_sha256(
            project_root=project_root, relative_paths=_CODE_PATHS
        ),
        universe_name=universe["name"],
        universe_frozen_as_of=universe["frozen_as_of"],
        candidate_symbols=tuple(sorted(candidates)),
        data_start=data_start,
        data_end=data_end,
        signal_timing="close",
        execution_timing="next_session_open",
        valuation_timing="close",
        folds=tuple(
            ResearchFoldV1(
                item.fold,
                item.train_start,
                item.train_end,
                item.validation_start,
                item.validation_end,
                item.test_start,
                item.test_end,
            )
            for item in folds
        ),
        cost_multipliers=tuple(sorted(float(value) for value in walk["cost_multipliers"])),
        selection_metric=walk["selection_metric"],
        inputs=tuple(sorted((
            dataframe_input_digest(
                name="bars", frame=bars, sort_by=("trade_date", "symbol"),
                date_column="trade_date",
            ),
            dataframe_input_digest(
                name="calendars", frame=calendars,
                sort_by=("market", "date"), date_column="date",
            ),
            dataframe_input_digest(
                name="instruments", frame=instruments, sort_by=("symbol",),
                date_column="list_date",
            ),
            dataframe_input_digest(
                name="research-prices", frame=prices,
                sort_by=("trade_date", "symbol"), date_column="trade_date",
            ),
        ), key=lambda item: item.name)),
        outputs=(),
        aggregate_metrics=tuple(sorted(aggregate.items())),
        caveats=caveats,
    )
    output, completed, reused = publish_lightweight_research_run(
        artifact_root=artifact_root, run=run, output_payloads=output_payloads
    )
    print(json.dumps({
        "output": str(output), "run_id": completed.run_id, "reused": reused,
        **report,
    }, ensure_ascii=False))
    return 0


def make_folds(
    *,
    start: dt.date,
    end: dt.date,
    train_months: int,
    validation_months: int,
    test_months: int,
    step_months: int,
) -> list[Fold]:
    if min(train_months, validation_months, test_months, step_months) <= 0:
        raise ValueError("walk-forward 月数必须为正")
    folds: list[Fold] = []
    train_start = _month_start(start)
    fold_number = 1
    while True:
        train_end = _add_months(train_start, train_months) - dt.timedelta(days=1)
        validation_start = train_end + dt.timedelta(days=1)
        validation_end = (
            _add_months(validation_start, validation_months) - dt.timedelta(days=1)
        )
        test_start = validation_end + dt.timedelta(days=1)
        test_end = _add_months(test_start, test_months) - dt.timedelta(days=1)
        if test_end > end:
            break
        folds.append(Fold(
            fold=fold_number,
            train_start=train_start,
            train_end=train_end,
            validation_start=validation_start,
            validation_end=validation_end,
            test_start=test_start,
            test_end=test_end,
        ))
        train_start = _add_months(train_start, step_months)
        fold_number += 1
    return folds


def evaluate_window(
    *,
    bars: pl.DataFrame,
    prices: pl.DataFrame,
    calendars: pl.DataFrame,
    instruments: pl.DataFrame,
    candidates: list[str],
    start: dt.date,
    end: dt.date,
    params: Parameters,
    strategy_config: dict[str, Any],
    strategy_kind: str,
    strategy_version: str = "1.0.0",
    costs: EtfCostModel,
    initial_cash: float,
    strategy_name: str,
    rebalance_months: int = 1,
) -> EtfDiagnosticSimulationResult:
    targets = build_window_targets(
        prices=prices,
        calendars=calendars,
        candidates=candidates,
        start=start,
        end=end,
        params=params,
        strategy_config=strategy_config,
        strategy_kind=strategy_kind,
        strategy_version=strategy_version,
        strategy_name=strategy_name,
        rebalance_months=rebalance_months,
    )
    return simulate_window(
        bars=bars,
        prices=prices,
        instruments=instruments,
        start=start,
        end=end,
        targets=targets,
        costs=costs,
        initial_cash=initial_cash,
        strategy_name=strategy_name,
    )


def build_window_targets(
    *,
    prices: pl.DataFrame,
    calendars: pl.DataFrame,
    candidates: list[str],
    start: dt.date,
    end: dt.date,
    params: Parameters,
    strategy_config: dict[str, Any],
    strategy_kind: str,
    strategy_version: str = "1.0.0",
    strategy_name: str,
    rebalance_months: int = 1,
) -> pl.DataFrame:
    """Compute one target schedule that all cost scenarios must share."""
    signal_dates = _monthly_signal_dates(
        prices,
        start=start,
        end=end,
        every_months=rebalance_months,
    )
    retention_buffer = strategy_config.get("selection_retention_buffer", 0)
    if (
        not isinstance(retention_buffer, int)
        or isinstance(retention_buffer, bool)
        or retention_buffer < 0
    ):
        raise ValueError("selection_retention_buffer 必须是非负整数")
    volatility_target = _volatility_target_spec(strategy_config)
    target_frames: list[pl.DataFrame] = []
    previous_symbols: tuple[str, ...] = ()
    for as_of in signal_dates:
        factors = compute_trend_factors_from_prices(
            prices,
            as_of=as_of,
            source=None,
            momentum_windows=tuple(strategy_config["momentum_windows"]),
            regression_window=params.regression_window,
            factor_version=strategy_config["factor_version"],
        )
        common = {
            "candidates": tuple(candidates),
            "top_k": params.top_k,
            "cash_buffer": strategy_config["cash_buffer"],
            "factor_version": strategy_config["factor_version"],
            "momentum_windows": tuple(strategy_config["momentum_windows"]),
            "regression_window": params.regression_window,
            "name": strategy_name,
            "version": strategy_version,
        }
        strategy: (
            EtfTrendStrategy
            | RegimeFilteredEtfTrendStrategy
            | BreadthFilteredEtfTrendStrategy
        )
        if strategy_kind == "etf_trend":
            strategy = EtfTrendStrategy(**common)
        elif strategy_kind == "etf_regime_trend":
            strategy = RegimeFilteredEtfTrendStrategy(
                **common, regime_symbol=strategy_config["regime_symbol"]
            )
        elif strategy_kind == "etf_breadth_regime_trend":
            strategy = BreadthFilteredEtfTrendStrategy(
                **common, breadth_window=strategy_config["breadth_window"]
            )
        else:
            raise ValueError(f"不支持的研究策略: {strategy_kind}")
        current_targets = strategy.target_weights(as_of, factors)
        if retention_buffer:
            retention_common = dict(common)
            retention_common["top_k"] = params.top_k + retention_buffer
            if strategy_kind == "etf_trend":
                retention_strategy: (
                    EtfTrendStrategy
                    | RegimeFilteredEtfTrendStrategy
                    | BreadthFilteredEtfTrendStrategy
                )
                retention_strategy = EtfTrendStrategy(**retention_common)
            elif strategy_kind == "etf_regime_trend":
                retention_strategy = RegimeFilteredEtfTrendStrategy(
                    **retention_common,
                    regime_symbol=strategy_config["regime_symbol"],
                )
            else:
                retention_strategy = BreadthFilteredEtfTrendStrategy(
                    **retention_common,
                    breadth_window=strategy_config["breadth_window"],
                )
            current_targets = retain_ranked_target_selection(
                current_targets=current_targets,
                retention_candidates=retention_strategy.target_weights(as_of, factors),
                previous_symbols=previous_symbols,
                top_k=params.top_k,
            )
        if volatility_target is not None:
            lookback, target_volatility, annualization_sessions = volatility_target
            current_targets = scale_target_weights_to_volatility(
                targets=current_targets,
                prices=prices,
                lookback_observations=lookback,
                annualized_target_volatility=target_volatility,
                annualization_sessions=annualization_sessions,
            )
        target_frames.append(current_targets)
        previous_symbols = tuple(
            current_targets.filter(pl.col("weight") > 0)
            .get_column("symbol")
            .to_list()
        )
    nonempty = [frame for frame in target_frames if not frame.is_empty()]
    targets = (
        schedule_next_trading_day(pl.concat(nonempty), calendars)
        if nonempty
        else _empty_scheduled_targets()
    ).filter(pl.col("execution_date").is_between(start, end, closed="both"))
    return targets.sort("execution_date", "symbol")


def build_equal_weight_targets(
    *,
    prices: pl.DataFrame,
    calendars: pl.DataFrame,
    candidates: list[str],
    start: dt.date,
    end: dt.date,
    cash_buffer: float,
    strategy_name: str,
    rebalance_months: int = 1,
) -> pl.DataFrame:
    """Build the same monthly schedule for the equal-weight S0 comparator."""
    available = pl.DataFrame({
        "symbol": candidates,
        "eligible": [True] * len(candidates),
    })
    strategy = EqualWeightStrategy(
        candidates=tuple(candidates),
        cash_buffer=cash_buffer,
        name=strategy_name,
    )
    target_frames = [
        strategy.target_weights(as_of, available)
        for as_of in _monthly_signal_dates(
            prices,
            start=start,
            end=end,
            every_months=rebalance_months,
        )
    ]
    targets = schedule_next_trading_day(pl.concat(target_frames), calendars).filter(
        pl.col("execution_date").is_between(start, end, closed="both")
    )
    return targets.sort("execution_date", "symbol")


def simulate_window(
    *,
    bars: pl.DataFrame,
    prices: pl.DataFrame,
    instruments: pl.DataFrame,
    start: dt.date,
    end: dt.date,
    targets: pl.DataFrame,
    costs: EtfCostModel,
    initial_cash: float,
    strategy_name: str,
) -> EtfDiagnosticSimulationResult:
    """Replay a precomputed target schedule under one cost scenario."""
    return simulate_etf_targets_with_diagnostics(
        bars=bars.filter(pl.col("trade_date").is_between(start, end, closed="both")),
        research_prices=prices.filter(
            pl.col("trade_date").is_between(start, end, closed="both")
        ),
        scheduled_targets=targets,
        instruments=instruments,
        initial_cash=initial_cash,
        costs=costs,
        strategy=strategy_name,
    )


def _inside(project_root: Path, value: Path, *, strict: bool = True) -> Path:
    candidate = value if value.is_absolute() else project_root / value
    resolved = candidate.resolve(strict=strict)
    if resolved != project_root and project_root not in resolved.parents:
        raise ValueError("research path must stay inside project root")
    return resolved


def _parquet_bytes(frame: pl.DataFrame) -> bytes:
    buffer = io.BytesIO()
    frame.write_parquet(buffer, compression="zstd", statistics=True)
    return buffer.getvalue()


def metrics(
    nav: pl.DataFrame,
    trades: pl.DataFrame,
    *,
    initial_cash: float,
    target_gaps: pl.DataFrame | None = None,
) -> dict[str, float]:
    unit = nav.get_column("unit_nav")
    returns = unit.pct_change().drop_nulls()
    standard_deviation = cast(float, returns.std()) if returns.len() > 1 else 0.0
    annualized_volatility = standard_deviation * math.sqrt(252)
    sharpe = (
        cast(float, returns.mean()) / standard_deviation * math.sqrt(252)
        if standard_deviation > 0
        else 0.0
    )
    drawdown = unit / unit.cum_max() - 1
    traded = trades.get_column("notional").sum()
    gross_traded_notional = 0.0 if traded is None else float(traded)
    unresolved_gaps = (
        target_gaps.filter(pl.col("gap_reason") != "NONE")
        if target_gaps is not None
        else None
    )
    gap_notional = (
        unresolved_gaps.get_column("absolute_notional_gap").drop_nulls().sum()
        if unresolved_gaps is not None
        else 0.0
    )
    return {
        "total_return": float(unit[-1] - 1),
        "sharpe": sharpe,
        "annualized_volatility": annualized_volatility,
        "max_drawdown": cast(float, drawdown.min()),
        "ending_equity": cast(float, nav.item(-1, "equity")),
        "cumulative_fees": cast(float, nav.item(-1, "cumulative_fees")),
        "trade_count": float(trades.height),
        "gross_traded_notional": gross_traded_notional,
        "one_way_turnover_on_initial_cash": (
            gross_traded_notional / (2 * initial_cash)
        ),
        "target_gap_count": float(
            0 if unresolved_gaps is None else unresolved_gaps.height
        ),
        "absolute_target_gap_notional": (
            0.0 if gap_notional is None else float(gap_notional)
        ),
    }


def _monthly_signal_dates(
    prices: pl.DataFrame,
    *,
    start: dt.date,
    end: dt.date,
    every_months: int = 1,
) -> list[dt.date]:
    if (
        not isinstance(every_months, int)
        or isinstance(every_months, bool)
        or every_months <= 0
    ):
        raise ValueError("every_months 必须是正整数")
    dates = prices.get_column("trade_date").unique().sort()
    prior = dates.filter(dates < start)
    selected = dates.filter((dates >= start) & (dates <= end))
    frame = pl.DataFrame({"date": selected}).with_columns(
        pl.col("date").dt.year().alias("year"),
        pl.col("date").dt.month().alias("month"),
    )
    month_ends = (
        frame.group_by("year", "month")
        .agg(pl.col("date").max())
        .sort("date")
        .get_column("date")
        .to_list()
    )[::every_months]
    if not prior.is_empty():
        return [cast(dt.date, prior.max()), *month_ends]
    return month_ends


def _costs(config: dict[str, Any], multiplier: float) -> EtfCostModel:
    cost = config["costs"]["etf"]
    return EtfCostModel(
        commission_rate=cost["commission_rate"] * multiplier,
        commission_min=cost["commission_min"] * multiplier,
        slippage=cost["slippage"] * multiplier,
        effective_from=cost["effective_from"],
    )


def _candidates(config: dict[str, Any]) -> list[str]:
    universe = config["universe"]
    return [
        symbol
        for group in ("wide", "industry", "hong_kong_theme")
        for symbol in universe[group]
    ]


def _volatility_target_spec(
    strategy_config: dict[str, Any],
) -> tuple[int, float, int] | None:
    section = strategy_config.get("volatility_target")
    if section is None:
        return None
    if not isinstance(section, dict) or set(section) != {
        "lookback_observations",
        "annualized_volatility",
        "annualization_sessions",
    }:
        raise ValueError("volatility_target 配置字段不完整或包含未知字段")
    lookback = section["lookback_observations"]
    target = section["annualized_volatility"]
    sessions = section["annualization_sessions"]
    if (
        not isinstance(lookback, int)
        or isinstance(lookback, bool)
        or lookback < 2
    ):
        raise ValueError("volatility_target.lookback_observations 必须至少为 2")
    if (
        not isinstance(target, float)
        or not math.isfinite(target)
        or not 0 < target < 1
    ):
        raise ValueError("volatility_target.annualized_volatility 必须在 (0, 1)")
    if (
        not isinstance(sessions, int)
        or isinstance(sessions, bool)
        or sessions <= 0
    ):
        raise ValueError("volatility_target.annualization_sessions 必须是正整数")
    return lookback, target, sessions


def _research_spec(config: dict[str, Any]) -> ResearchSpec:
    section = config.get("research")
    if section is None:
        return ResearchSpec(
            hypothesis_id=_HYPOTHESIS_ID,
            hypothesis=_HYPOTHESIS,
            strategy_kind=_STRATEGY_KIND,
            strategy_version="1.0.0",
            conclusion="RESEARCH_ONLY",
            random_seed=0,
        )
    required = {
        "hypothesis_id",
        "hypothesis",
        "strategy_kind",
        "strategy_version",
        "conclusion",
        "random_seed",
    }
    if set(section) != required:
        raise ValueError("research 配置字段不完整或包含未知字段")
    strategy_kind = section["strategy_kind"]
    if strategy_kind not in {
        "etf_trend",
        "etf_regime_trend",
        "etf_breadth_regime_trend",
    }:
        raise ValueError("research.strategy_kind 不受支持")
    conclusion = section["conclusion"]
    if conclusion not in {"REJECTED", "RESEARCH_ONLY"}:
        raise ValueError("研究运行结论只能是 REJECTED 或 RESEARCH_ONLY")
    return ResearchSpec(
        hypothesis_id=section["hypothesis_id"],
        hypothesis=section["hypothesis"],
        strategy_kind=cast(
            Literal[
                "etf_trend", "etf_regime_trend", "etf_breadth_regime_trend"
            ],
            strategy_kind,
        ),
        strategy_version=section["strategy_version"],
        conclusion=cast(Literal["REJECTED", "RESEARCH_ONLY"], conclusion),
        random_seed=section["random_seed"],
    )


def _require_symbol_coverage(
    frame: pl.DataFrame, candidates: list[str], label: str
) -> None:
    missing = sorted(set(candidates) - set(frame.get_column("symbol").unique().to_list()))
    if missing:
        raise ValueError(f"{label}缺少证券: " + ", ".join(missing))


def _month_start(value: dt.date) -> dt.date:
    return value.replace(day=1)


def _add_months(value: dt.date, months: int) -> dt.date:
    month_index = value.year * 12 + value.month - 1 + months
    return dt.date(month_index // 12, month_index % 12 + 1, 1)


def _empty_scheduled_targets() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "as_of": pl.Date,
            "strategy": pl.String,
            "strategy_version": pl.String,
            "symbol": pl.String,
            "weight": pl.Float64,
            "execution_date": pl.Date,
        }
    )


if __name__ == "__main__":
    raise SystemExit(main())
