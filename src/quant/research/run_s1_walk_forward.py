"""ETF 趋势策略的滚动验证、冻结测试与成本压力。"""

import argparse
import datetime as dt
import json
import math
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence, cast

import polars as pl

from quant.backtest import (
    EtfCostModel,
    SimulationResult,
    schedule_next_trading_day,
    simulate_etf_targets,
)
from quant.factors import compute_trend_factors_from_prices
from quant.strategies import EtfTrendStrategy


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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行 M2 S1 walk-forward")
    parser.add_argument(
        "--config", type=Path, default=Path("configs/research/m2_baseline.toml")
    )
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    args = parser.parse_args(argv)
    with args.config.open("rb") as stream:
        config: dict[str, Any] = tomllib.load(stream)
    walk = config["walk_forward"]
    if not walk["enabled"]:
        raise ValueError("walk_forward.enabled 必须显式为 true")
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
        args.data_root / "clean" / "bar_1d" / "date=*" / "data.parquet"
    ).filter(
        pl.col("symbol").is_in(candidates)
        & pl.col("trade_date").is_between(data_start, data_end, closed="both")
        & (
            ((pl.col("trade_date") < dt.date(2026, 1, 1)) & (pl.col("source") == "akshare"))
            | ((pl.col("trade_date") >= dt.date(2026, 1, 1)) & (pl.col("source") == "baostock"))
        )
    )
    prices = pl.read_parquet(
        args.data_root / "clean" / "research_price_1d" / "date=*" / "data.parquet"
    ).filter(
        pl.col("symbol").is_in(candidates)
        & (pl.col("adjustment_method") == "TOTAL_RETURN_DIVIDEND")
        & pl.col("trade_date").is_between(data_start, data_end, closed="both")
    )
    calendars = pl.concat([
        pl.read_parquet(
            args.data_root / "clean" / "trade_calendar" / f"market={market}" / "data.parquet"
        )
        for market in ("SH", "SZ")
    ])
    instruments = pl.concat([
        pl.read_parquet(
            args.data_root / "clean" / "instrument" / f"market={market}" / "data.parquet"
        )
        for market in ("SH", "SZ")
    ]).filter(pl.col("symbol").is_in(candidates))
    _require_symbol_coverage(bars, candidates, "成交行情")
    _require_symbol_coverage(prices, candidates, "总回报价格")

    strategy_config = config["strategy"]["etf_trend"]
    grid = [
        Parameters(top_k=top_k, regression_window=window)
        for top_k in walk["grid"]["top_k"]
        for window in walk["grid"]["regression_window"]
    ]
    base_costs = _costs(config, 1.0)
    initial_cash = config["backtest"]["initial_cash"]
    fold_reports: list[dict[str, object]] = []
    one_x_results: list[dict[str, float]] = []
    nav_outputs: list[pl.DataFrame] = []
    trade_outputs: list[pl.DataFrame] = []

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
                strategy_name=f"s1_fold_{fold.fold}_validation",
            )
            validation_scores.append((params, metrics(validation.nav)))
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
        for multiplier in walk["cost_multipliers"]:
            result = evaluate_window(
                bars=bars,
                prices=prices,
                calendars=calendars,
                instruments=instruments,
                candidates=candidates,
                start=fold.test_start,
                end=fold.test_end,
                params=chosen,
                strategy_config=strategy_config,
                costs=_costs(config, multiplier),
                initial_cash=initial_cash,
                strategy_name=f"s1_fold_{fold.fold}_test_{multiplier}x",
            )
            result_metrics = metrics(result.nav)
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
        if test_one_x is None:
            raise ValueError("成本压力必须包含 1.0 倍场景")
        one_x_results.append(test_one_x)
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
        })

    compounded_return = math.prod(
        1 + result["total_return"] for result in one_x_results
    ) - 1
    report = {
        "config": str(args.config),
        "selection_metric": walk["selection_metric"],
        "folds": fold_reports,
        "aggregate_1x": {
            "compounded_test_return": compounded_return,
            "positive_folds": sum(
                result["total_return"] > 0 for result in one_x_results
            ),
            "fold_count": len(one_x_results),
            "worst_fold_return": min(
                result["total_return"] for result in one_x_results
            ),
            "worst_fold_max_drawdown": min(
                result["max_drawdown"] for result in one_x_results
            ),
            "selected_parameters": [
                fold["selected_parameters"] for fold in fold_reports
            ],
        },
        "caveats": [
            "参数仅在每折验证集选择，测试集不参与选择",
            "规则策略的训练段仅用于因子预热，不拟合模型参数",
            "ETF_POOL_M2_V1 于 2026-07-12 才冻结，历史回看仍有候选池后见偏差",
            "尚未实现 ETF 涨跌停拒单",
            "成本参数尚未用券商账单校准",
        ],
    }
    output = args.artifact_root / "research" / "m2" / "s1_walk_forward"
    output.mkdir(parents=True, exist_ok=True)
    pl.concat(nav_outputs, how="vertical_relaxed").write_parquet(output / "test_nav.parquet")
    pl.concat(trade_outputs, how="vertical_relaxed").write_parquet(
        output / "test_trades.parquet"
    )
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"output": str(output), **report}, ensure_ascii=False))
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
    costs: EtfCostModel,
    initial_cash: float,
    strategy_name: str,
) -> SimulationResult:
    signal_dates = _monthly_signal_dates(prices, start=start, end=end)
    target_frames: list[pl.DataFrame] = []
    for as_of in signal_dates:
        factors = compute_trend_factors_from_prices(
            prices,
            as_of=as_of,
            source=None,
            momentum_windows=tuple(strategy_config["momentum_windows"]),
            regression_window=params.regression_window,
            factor_version=strategy_config["factor_version"],
        )
        strategy = EtfTrendStrategy(
            candidates=tuple(candidates),
            top_k=params.top_k,
            cash_buffer=strategy_config["cash_buffer"],
            factor_version=strategy_config["factor_version"],
            momentum_windows=tuple(strategy_config["momentum_windows"]),
            regression_window=params.regression_window,
            name=strategy_name,
        )
        target_frames.append(strategy.target_weights(as_of, factors))
    nonempty = [frame for frame in target_frames if not frame.is_empty()]
    targets = (
        schedule_next_trading_day(pl.concat(nonempty), calendars)
        if nonempty
        else _empty_scheduled_targets()
    ).filter(pl.col("execution_date").is_between(start, end, closed="both"))
    return simulate_etf_targets(
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


def metrics(nav: pl.DataFrame) -> dict[str, float]:
    unit = nav.get_column("unit_nav")
    returns = unit.pct_change().drop_nulls()
    standard_deviation = cast(float, returns.std()) if returns.len() > 1 else 0.0
    sharpe = (
        cast(float, returns.mean()) / standard_deviation * math.sqrt(252)
        if standard_deviation > 0
        else 0.0
    )
    drawdown = unit / unit.cum_max() - 1
    return {
        "total_return": float(unit[-1] - 1),
        "sharpe": sharpe,
        "max_drawdown": cast(float, drawdown.min()),
        "ending_equity": cast(float, nav.item(-1, "equity")),
        "cumulative_fees": cast(float, nav.item(-1, "cumulative_fees")),
    }


def _monthly_signal_dates(
    prices: pl.DataFrame, *, start: dt.date, end: dt.date
) -> list[dt.date]:
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
    )
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
