"""Run the independently registered B31 announcement-event experiment."""

import argparse
import copy
import hashlib
import io
import json
import math
import tomllib
from pathlib import Path
from typing import Any, Literal

import polars as pl

from quant.data.etf_paper_inputs import etf_session_states, read_etf_dividends
from quant.data.etf_research_inputs import read_etf_research_inputs
from quant.data.financial_repository import TushareFinancialHistoryQuery, read_tushare_financial_history
from quant.data.refresh_stocks import read_stock_data
from quant.data.stock_execution_inputs import prepare_stock_execution_inputs, stock_session_states
from quant.data.stock_name_history import read_name_history
from quant.research.classic_monthly_baseline import replay
from quant.research.lightweight_run import (
    LightweightResearchRunV1, ResearchFoldV1, canonical_json_bytes, compute_code_sha256,
    dataframe_input_digest, publish_lightweight_research_run,
)
from quant.research.pead_events import build_events, replay_events
from quant.research.run_classic_factors import select_frozen_liquid_universe
from quant.research.run_s1_walk_forward import metrics
from quant.settings import resolve_data_root


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/research/b31_pead40_20260909.toml"))
    args = parser.parse_args()
    root = Path.cwd()
    cfg_path = args.config.resolve()
    config = tomllib.loads(cfg_path.read_text(encoding="utf-8-sig"))
    data_root = resolve_data_root(None, base=root)
    data, universe, portfolio = config["data"], config["universe"], config["portfolio"]
    folds = tuple(ResearchFoldV1(i, **f) for i, f in enumerate(config["walk_forward"]["folds"], 1))
    refresh = root / data["refresh_config"]
    freeze = read_stock_data(data_root=data_root, config=refresh, table="bar_1d",
                            start=universe["freeze_start"], end=universe["freeze_end"])
    candidates = select_frozen_liquid_universe(freeze, top_n=800, minimum_observations=120,
                                             minimum_average_amount=20_000_000)
    bars = read_stock_data(data_root=data_root, config=refresh, table="bar_1d",
                          start=data["warmup_start"], end=data["research_end"], symbols=list(candidates))
    benchmark, _, calendar, benchmark_instruments = read_etf_research_inputs(
        data_root, [portfolio["benchmark"]], data["warmup_start"], data["research_end"])
    sessions = tuple(sorted(calendar.filter(pl.col("is_open"))["date"].unique().to_list()))
    history = read_tushare_financial_history(data_root=data_root, query=TushareFinancialHistoryQuery(
        snapshot_id=data["financial_snapshot"], dataset="income", start_period=data["history_start"],
        end_period=data["research_end"], symbols=candidates))
    names = read_name_history(data_root, list(candidates), data["research_end"])
    events = build_events(history=history, bars=bars, names=names, sessions=sessions,
                          start=data["research_start"], end=data["research_end"],
                          minimum_threshold_events=config["event"]["minimum_threshold_events"])
    print(f"Frozen events: {events.height}; selected: {events.filter('selected').height}", flush=True)
    usable = pl.concat([events.filter(pl.col("execution_date").is_between(f.test_start, f.test_end)
        & (pl.col("expiry_date") <= f.test_end) & pl.col("threshold").is_not_null())
        .with_columns(pl.lit(f.fold).alias("fold")) for f in folds])
    symbols = sorted(usable["symbol"].unique().to_list())
    order_dates = [d for d in sessions if folds[0].test_start <= d <= folds[-1].test_end]
    print(f"Execution data: {len(symbols)} symbols, {len(order_dates)} daily sessions", flush=True)
    limits, suspensions, dividends, instruments = prepare_stock_execution_inputs(
        data_root=data_root, symbols=symbols, execution_dates=order_dates,
        start=folds[0].test_start, end=folds[-1].test_end,
        output=data_root / "clean/stock_execution" / config["research"]["hypothesis_id"])
    dividends = dividends.with_columns((pl.col("div_cash") * .8).alias("div_cash"))
    benchmark_dividends = read_etf_dividends(data_root, [portfolio["benchmark"]], folds[0].test_start)
    stock_bars = bars.filter(pl.col("symbol").is_in(symbols))
    results: list[dict[str, Any]] = []
    navs: list[pl.DataFrame] = []
    trades: list[pl.DataFrame] = []
    rejections: list[pl.DataFrame] = []
    decisions: list[pl.DataFrame] = []
    for fold in folds:
        dates = [d for d in sessions if fold.test_start <= d <= fold.test_end]
        fold_events = usable.filter(pl.col("fold") == fold.fold).drop("fold")
        for multiplier in portfolio["cost_multipliers"]:
            scenario = copy.deepcopy(config)
            for costs in scenario["costs"].values():
                for key in ("commission_rate", "commission_min", "slippage"):
                    costs[key] *= multiplier
            states = stock_session_states(bars=stock_bars, limits=limits, suspensions=suspensions,
                sessions=dates, symbols=symbols, execution_dates=dates,
                slippage=scenario["costs"]["a_share"]["slippage"])
            for comparison in ("pead40", "all_events", "510300"):
                if comparison == "510300":
                    targets = pl.DataFrame({"as_of": [max(d for d in sessions if d < dates[0])],
                        "execution_date": [dates[0]], "symbol": [portfolio["benchmark"]],
                        "strategy": [comparison], "strategy_version": ["v1"], "weight": [1.0]})
                    nav, fills, rejects = replay(bars=benchmark, calendar=calendar,
                        instruments=benchmark_instruments, targets=targets, dividends=benchmark_dividends,
                        market_states=etf_session_states(benchmark, benchmark_dividends,
                            slippage=scenario["costs"]["etf"]["slippage"]),
                        config=scenario, sessions=dates, name=comparison)
                    decision = None
                else:
                    selected = fold_events.filter("selected") if comparison == "pead40" else fold_events
                    nav, fills, rejects, decision = replay_events(events=selected, bars=stock_bars,
                        calendar=calendar, instruments=instruments, dividends=dividends,
                        market_states=states, sessions=dates, config=scenario, name=comparison)
                tags = {"fold": fold.fold, "cost_multiplier": multiplier, "comparison": comparison}
                results.append({**tags, **metrics(nav, fills, initial_cash=portfolio["initial_cash"]),
                    "average_position_count": nav["position_count"].mean(),
                    "average_invested_fraction": (nav["market_value"] / nav["equity"]).mean(),
                    "rejections": rejects.height})
                for collection, frame in ((navs, nav), (trades, fills), (rejections, rejects)):
                    collection.append(frame.with_columns(*(pl.lit(v).alias(k) for k, v in tags.items())))
                if decision is not None:
                    decisions.append(decision.with_columns(*(pl.lit(v).alias(k) for k, v in tags.items())))
                print(f"Completed fold {fold.fold} {comparison} {multiplier}x", flush=True)
    def compounded(name, multiplier):
        return math.prod(1 + r["total_return"] for r in results
                         if r["comparison"] == name and r["cost_multiplier"] == multiplier) - 1
    positive_folds = sum(next(r["total_return"] for r in results if r["fold"] == f.fold
        and r["comparison"] == "pead40" and r["cost_multiplier"] == 1.0) >
        next(r["total_return"] for r in results if r["fold"] == f.fold
        and r["comparison"] == "all_events" and r["cost_multiplier"] == 1.0) for f in folds)
    excess = compounded("pead40", 1.0) - compounded("all_events", 1.0)
    passed = (positive_folds >= 2 and excess > 0 and compounded("pead40", 2.0) > 0
              and all(r["max_drawdown"] >= -.30 for r in results
                      if r["comparison"] == "pead40" and r["cost_multiplier"] == 2.0))
    conclusion: Literal["RESEARCH_ONLY", "REJECTED"] = "RESEARCH_ONLY" if passed else "REJECTED"
    caveat = "Previously examined market periods and a historical financial snapshot; first-observed announcement dates are not original-vintage filings."
    report = {"hypothesis_id": config["research"]["hypothesis_id"], "conclusion": conclusion,
        "results": results, "events": events.height, "usable_events": usable.height,
        "selected_events": usable.filter("selected").height, "positive_excess_folds": positive_folds,
        "excess_1x_all_events": excess, "compounded": {str(m): {n: compounded(n, m)
            for n in ("pead40", "all_events", "510300")} for m in portfolio["cost_multipliers"]},
        "caveat": caveat}
    outputs = {"report.json": canonical_json_bytes(report)}
    for name, frame in (("events", events), ("usable_events", usable),
                        ("nav", pl.concat(navs, how="diagonal_relaxed")),
                        ("trades", pl.concat(trades, how="diagonal_relaxed")),
                        ("rejections", pl.concat(rejections, how="diagonal_relaxed")),
                        ("decisions", pl.concat(decisions, how="diagonal_relaxed"))):
        stream = io.BytesIO()
        frame.write_parquet(stream)
        outputs[f"{name}.parquet"] = stream.getvalue()
    inputs = tuple(dataframe_input_digest(name=n, frame=f, sort_by=s, date_column=d) for n, f, s, d in (
        ("freeze", freeze, ("trade_date", "symbol"), "trade_date"),
        ("bars", bars, ("trade_date", "symbol"), "trade_date"),
        ("financials", history, ("symbol", "end_date", "available_date"), "available_date"),
        ("names", names, ("symbol", "start_date"), "start_date"),
        ("calendar", calendar, ("date", "market"), "date"),
        ("limits", limits, ("trade_date", "symbol"), "trade_date"),
        ("suspensions", suspensions, ("trade_date", "symbol"), "trade_date"),
        ("dividends", dividends, ("ex_date", "symbol"), "ex_date"),
        ("instruments", instruments, ("symbol",), "list_date"),
        ("benchmark", benchmark, ("trade_date", "symbol"), "trade_date"),
        ("benchmark-dividends", benchmark_dividends, ("ex_date", "symbol"), "ex_date"),
    ))
    paths = ("src/quant/research/run_pead_events.py", "src/quant/research/pead_events.py",
        "src/quant/research/monthly_sue.py", "src/quant/factors/earnings_surprise.py",
        "src/quant/research/classic_monthly_baseline.py", "src/quant/backtest/daily_account.py",
        "src/quant/backtest/daily_simulator.py", "src/quant/backtest/costs.py",
        "src/quant/backtest/rules.py", "src/quant/data/financial_pit.py",
        "src/quant/data/financial_clean.py", "src/quant/data/stock_execution_inputs.py")
    run = LightweightResearchRunV1(schema_version="lightweight-research-run-v1", run_id="",
        hypothesis_id=config["research"]["hypothesis_id"], hypothesis=config["research"]["hypothesis"],
        strategy_name=config["research"]["strategy_name"], strategy_version="v1", conclusion=conclusion,
        random_seed=config["research"]["random_seed"], config_relative_path=args.config.as_posix(),
        config_sha256=hashlib.sha256(cfg_path.read_bytes()).hexdigest(),
        code_sha256=compute_code_sha256(project_root=root, relative_paths=paths),
        universe_name=universe["name"], universe_frozen_as_of=universe["freeze_end"], candidate_symbols=candidates,
        data_start=data["history_start"], data_end=data["research_end"], signal_timing="close",
        execution_timing="next_session_open", valuation_timing="close", folds=folds,
        cost_multipliers=tuple(portfolio["cost_multipliers"]), selection_metric="fixed_pead40",
        inputs=tuple(sorted(inputs, key=lambda i: i.name)), outputs=(),
        aggregate_metrics=(("excess_return_1x", excess), ("net_return_1x", compounded("pead40", 1.0)),
                           ("net_return_2x", compounded("pead40", 2.0))), caveats=(caveat,))
    output, completed, reused = publish_lightweight_research_run(artifact_root=root / "artifacts", run=run,
                                                               output_payloads=outputs)
    print(json.dumps({"output": str(output), "run_id": completed.run_id, "reused": reused, **report}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
