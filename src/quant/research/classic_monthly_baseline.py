"""Monthly z-score baseline implementation used by the existing composite CLI."""

import copy
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Literal

import polars as pl

from quant.backtest.daily_account import advance
from quant.data.etf_paper_inputs import etf_session_states, read_etf_dividends
from quant.data.etf_research_inputs import read_etf_research_inputs
from quant.data.refresh_stocks import read_stock_data
from quant.data.stock_execution_inputs import prepare_stock_execution_inputs, stock_session_states
from quant.factors import compute_classic_daily_factors
from quant.research.classic_factor_composite import (
    build_equal_weight_zscore_composite, build_monthly_zscore_targets,
)
from quant.research.classic_factor_evaluation import evaluate_factor_period
from quant.research.factor_labels import build_next_open_factor_labels
from quant.research.lightweight_run import (
    LightweightResearchRunV1, ResearchFoldV1, canonical_json_bytes, compute_code_sha256,
    dataframe_input_digest, publish_lightweight_research_run,
)
from quant.research.run_classic_factors import select_frozen_liquid_universe
from quant.research.run_s1_walk_forward import metrics

CODE_PATHS = (
    "src/quant/research/run_classic_factor_composite.py",
    "src/quant/research/classic_monthly_baseline.py",
    "src/quant/research/classic_factor_composite.py",
    "src/quant/research/run_classic_factors.py",
    "src/quant/research/run_s1_walk_forward.py",
    "src/quant/factors/classic.py",
    "src/quant/research/factor_labels.py",
    "src/quant/research/classic_factor_evaluation.py",
    "src/quant/data/mappers.py",
    "src/quant/backtest/daily_account.py",
    "src/quant/backtest/daily_simulator.py",
    "src/quant/backtest/costs.py",
    "src/quant/backtest/rules.py",
    "src/quant/data/refresh_stocks.py",
    "src/quant/data/stock_execution_inputs.py",
    "src/quant/data/etf_paper_inputs.py",
    "src/quant/data/etf_research_inputs.py",
)


def replay(
    *, bars: pl.DataFrame, calendar: pl.DataFrame, instruments: pl.DataFrame,
    targets: pl.DataFrame, dividends: pl.DataFrame, market_states: dict,
    config: dict[str, Any], sessions: list[dt.date], name: str,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Use the same cash/receivable/lot account for the strategy and comparator."""
    account_config = {"paper": {"name": name, "auto_trade": False,
                               "initial_cash": config["portfolio"]["initial_cash"]},
                      "costs": config["costs"]}
    state: dict[str, Any] = {"holdings": {}, "cash": config["portfolio"]["initial_cash"],
                             "receivables": [], "pending": [], "nav": []}
    by_date = {key[0]: value for key, value in bars.partition_by("trade_date", as_dict=True).items()}
    target_dates = {key[0]: value for key, value in targets.partition_by("execution_date", as_dict=True).items()}
    empty_bars = bars.head(0)
    trades, rejections = [], []
    for date in sessions:
        batch = target_dates.get(date)
        state["pending"] = ([] if batch is None else batch.with_columns(
            pl.col("as_of").cast(pl.String), pl.col("execution_date").cast(pl.String),
        ).to_dicts())
        today_bars = by_date.get(date, empty_bars)
        missing = (set() if batch is None else set(batch.get_column("symbol"))) - set(
            today_bars.get_column("symbol")) - set(state["holdings"])
        if missing:
            prior_marks = bars.filter(pl.col("symbol").is_in(missing) & (pl.col("trade_date") < date))
            prior_marks = prior_marks.sort("trade_date").unique("symbol", keep="last")
            today_bars = pl.concat([today_bars, prior_marks])
        state, result = advance(
            date=date, state=state, bars=today_bars, calendar=calendar,
            instruments=instruments, market_states=market_states, dividends=dividends,
            config=account_config,
        )
        state["nav"][-1]["position_count"] = len(state["holdings"])
        state["nav"][-1]["missing_target_positions"] = (
            len(set(batch.get_column("symbol")) - set(state["holdings"])) if batch is not None else None
        )
        trades.append(result.trades)
        rejections.append(result.rejections)
    return (pl.DataFrame(state["nav"]).with_columns(pl.col("date").str.to_date()),
            pl.concat(trades, how="vertical_relaxed"), pl.concat(rejections, how="vertical_relaxed"))


def run_baseline(
    *, config: dict[str, Any], config_path: Path, project_root: Path,
    data_root: Path, artifact_root: Path,
) -> int:
    data, universe, portfolio = config["data"], config["universe"], config["portfolio"]
    if (len(config["walk_forward"]["folds"]) != 1
        or config["composite"]["standard_deviation_ddof"] != 0
        or config["composite"]["winsorization"] != "none"
        or len(config["factors"]["names"]) != len(config["factors"]["directions"])
        or portfolio["cost_multipliers"] != [0.5, 1.0, 2.0]):
        raise ValueError("Unsupported monthly baseline configuration")
    fold = config["walk_forward"]["folds"][0]
    ResearchFoldV1(1, **fold)
    start, end = fold["test_start"], fold["test_end"]
    refresh_config = project_root / data["refresh_config"]
    freeze_bars = read_stock_data(data_root=data_root, config=refresh_config, table="bar_1d",
                                 start=universe["freeze_start"], end=universe["freeze_end"])
    candidates = select_frozen_liquid_universe(
        freeze_bars, top_n=universe["top_n"], minimum_observations=universe["minimum_observations"],
        minimum_average_amount=universe["minimum_average_amount"],
    )
    bars = read_stock_data(data_root=data_root, config=refresh_config, table="bar_1d",
                          start=data["warmup_start"], end=end, symbols=list(candidates))
    benchmark_bars, _, calendar, benchmark_instruments = read_etf_research_inputs(
        data_root, [portfolio["benchmark"]], data["warmup_start"], end,
    )
    all_sessions = tuple(sorted(calendar.filter(pl.col("is_open")).get_column("date").unique().to_list()))
    sessions = [date for date in all_sessions if start <= date <= end]
    factors = compute_classic_daily_factors(bars)
    directions = tuple(zip(config["factors"]["names"], config["factors"]["directions"]))
    eligible = factors.filter((pl.col("history_rows") >= config["factors"]["minimum_history_rows"])
                              & (pl.col("liquidity_20") >= universe["minimum_average_amount"]))
    scored = build_equal_weight_zscore_composite(eligible, component_directions=directions)
    targets = build_monthly_zscore_targets(
        scored, sessions=all_sessions, start=start, end=end, top_k=portfolio["top_k"],
        strategy_name=config["research"]["strategy_name"],
    )
    selected = sorted(targets.get_column("symbol").unique().to_list())
    execution_dates = sorted(targets.get_column("execution_date").unique().to_list())
    limits, suspensions, dividends, instruments = prepare_stock_execution_inputs(
        data_root=data_root, symbols=selected, execution_dates=execution_dates, start=start, end=end,
        output=data_root / "clean/stock_execution/a7_20260909",
    )
    dividends = dividends.with_columns((pl.col("div_cash") * (1 - portfolio["stock_dividend_withholding"])).alias("div_cash"))
    benchmark_dividends = read_etf_dividends(data_root, [portfolio["benchmark"]], start)
    benchmark_name = "a7_510300_buy_hold"
    benchmark_targets = pl.DataFrame({
        "as_of": [max(date for date in all_sessions if date < sessions[0])],
        "execution_date": [sessions[0]], "symbol": [portfolio["benchmark"]],
        "strategy": [benchmark_name], "strategy_version": ["v1"], "weight": [1.0],
    })
    stock_bars = bars.filter(pl.col("symbol").is_in(selected))
    results: list[dict[str, Any]] = []
    navs: list[pl.DataFrame] = []
    trades: list[pl.DataFrame] = []
    rejects: list[pl.DataFrame] = []
    for multiplier in portfolio["cost_multipliers"]:
        scenario = copy.deepcopy(config)
        for model in scenario["costs"].values():
            for key in ("commission_rate", "commission_min", "slippage"):
                model[key] *= multiplier
        stock_states = stock_session_states(
            bars=stock_bars, limits=limits, suspensions=suspensions, sessions=sessions,
            symbols=selected, execution_dates=execution_dates,
            slippage=scenario["costs"]["a_share"]["slippage"],
        )
        benchmark_states = etf_session_states(benchmark_bars, benchmark_dividends,
                                              slippage=scenario["costs"]["etf"]["slippage"])
        for comparison, bar_data, master, weights, events, states, name in (
            ("top50", stock_bars, instruments, targets, dividends, stock_states, config["research"]["strategy_name"]),
            ("510300", benchmark_bars, benchmark_instruments, benchmark_targets, benchmark_dividends, benchmark_states, benchmark_name),
        ):
            nav, fills, rejected = replay(bars=bar_data, calendar=calendar, instruments=master,
                targets=weights, dividends=events, market_states=states, config=scenario,
                sessions=sessions, name=name)
            scores = metrics(nav, fills, initial_cash=portfolio["initial_cash"])
            # The shared metric helper's optional gap diagnostics were not requested here.
            scores.pop("target_gap_count", None)
            scores.pop("absolute_target_gap_notional", None)
            results.append({"comparison": comparison, "cost_multiplier": multiplier,
                            "rejected_orders": rejected.height,
                            "average_position_count": nav.get_column("position_count").mean(),
                            "minimum_position_count": nav.get_column("position_count").min(),
                            "maximum_missing_targets_on_rebalance": nav.get_column("missing_target_positions").max(),
                            **scores})
            for collection, frame in ((navs, nav), (trades, fills), (rejects, rejected)):
                collection.append(frame.with_columns(pl.lit(comparison).alias("comparison"),
                                                     pl.lit(multiplier).alias("cost_multiplier")))
            print(f"Completed {comparison} cost {multiplier}x", flush=True)
    # Direction diagnostics do not select or alter the already frozen component weights.
    panel = build_next_open_factor_labels(factor_values=scored, bars=bars,
                                          sessions=all_sessions, horizons=(20,))
    diagnostic_rows = []
    for label, period_start, period_end in (
        ("train", fold["train_start"], fold["train_end"]),
        ("validation", fold["validation_start"], fold["validation_end"]),
        ("test", start, end),
    ):
        for factor, direction in (*directions, ("equal_zscore", 1)):
            _, _, score = evaluate_factor_period(panel, factor=factor, horizon=20,
                start_date=period_start, end_date=period_end, minimum_symbols=config["factors"]["minimum_daily_symbols"],
                direction=direction)
            diagnostic_rows.append({"period": label, "factor": factor, "direction": direction, **score})
    one = next(r for r in results if r["comparison"] == "top50" and r["cost_multiplier"] == 1.0)
    two = next(r for r in results if r["comparison"] == "top50" and r["cost_multiplier"] == 2.0)
    base = next(r for r in results if r["comparison"] == "510300" and r["cost_multiplier"] == 1.0)
    excess = one["total_return"] - base["total_return"]
    conclusion: Literal["RESEARCH_ONLY", "REJECTED"] = "RESEARCH_ONLY" if one["total_return"] > 0 and two["total_return"] > 0 and excess > 0 else "REJECTED"
    report = {"hypothesis_id": config["research"]["hypothesis_id"], "conclusion": conclusion,
              "period": [str(start), str(end)], "sessions": len(sessions), "universe": len(candidates),
              "selected_symbols": len(selected), "rebalance_count": len(execution_dates),
              "results": results, "factor_diagnostics": diagnostic_rows, "excess_return_1x": excess,
              "dividend_withholding_assumption": portfolio["stock_dividend_withholding"],
              "caveat": "The component selection used earlier research; this is an exploratory baseline."}
    outputs = {"report.json": canonical_json_bytes(report)}
    for name, frame in (("nav", pl.concat(navs, how="vertical_relaxed")),
                        ("trades", pl.concat(trades, how="vertical_relaxed")),
                        ("rejections", pl.concat(rejects, how="vertical_relaxed")),
                        ("targets", targets), ("benchmark_targets", benchmark_targets)):
        buffer = io.BytesIO()
        frame.write_parquet(buffer)
        outputs[f"{name}.parquet"] = buffer.getvalue()
    run = LightweightResearchRunV1(
        schema_version="lightweight-research-run-v1", run_id="",
        hypothesis_id=config["research"]["hypothesis_id"], hypothesis=config["research"]["hypothesis"],
        strategy_name=config["research"]["strategy_name"], strategy_version="v1", conclusion=conclusion,
        random_seed=config["research"]["random_seed"],
        config_relative_path=config_path.relative_to(project_root).as_posix(),
        config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(),
        code_sha256=compute_code_sha256(project_root=project_root, relative_paths=CODE_PATHS),
        universe_name=universe["name"], universe_frozen_as_of=universe["freeze_end"],
        candidate_symbols=candidates, data_start=data["warmup_start"], data_end=end,
        signal_timing="close", execution_timing="next_session_open", valuation_timing="close",
        folds=(ResearchFoldV1(1, **fold),), cost_multipliers=tuple(portfolio["cost_multipliers"]),
        selection_metric="fixed_equal_zscore",
        inputs=tuple(sorted((dataframe_input_digest(name=name, frame=frame, sort_by=sort, date_column=date)
                     for name, frame, sort, date in (
                         ("bars", bars, ("trade_date", "symbol"), "trade_date"),
                         ("benchmark-bars", benchmark_bars, ("trade_date", "symbol"), "trade_date"),
                         ("benchmark-dividends", benchmark_dividends, ("ex_date", "symbol"), "ex_date"),
                         ("freeze-bars", freeze_bars, ("trade_date", "symbol"), "trade_date"),
                         ("calendar", calendar, ("date", "market"), "date"),
                         ("dividends", dividends, ("ex_date", "symbol"), "ex_date"),
                         ("instruments", instruments, ("symbol",), "list_date"),
                         ("limits", limits, ("trade_date", "symbol"), "trade_date"),
                         ("suspensions", suspensions, ("trade_date", "symbol"), "trade_date"),
                     )), key=lambda item: item.name)), outputs=(), aggregate_metrics=(
                         ("excess_return_1x", excess), ("net_return_1x", one["total_return"]),
                         ("net_return_2x", two["total_return"])),
        caveats=(report["caveat"],),
    )
    output, completed, reused = publish_lightweight_research_run(artifact_root=artifact_root, run=run, output_payloads=outputs)
    print(json.dumps({"output": str(output), "run_id": completed.run_id, "reused": reused,
                      "conclusion": conclusion, "results": results}, ensure_ascii=False))
    return 0
