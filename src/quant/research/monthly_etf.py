"""Fixed Faber/relative-momentum research through the shared daily account."""

import argparse
import copy
import datetime as dt
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
from quant.data.publish_cross_asset_etfs import read_cross_asset_etfs
from quant.research.classic_monthly_baseline import replay
from quant.research.lightweight_run import (
    LightweightResearchRunV1, ResearchFoldV1, canonical_json_bytes, compute_code_sha256,
    dataframe_input_digest, publish_lightweight_research_run,
)
from quant.research.run_s1_walk_forward import metrics
from quant.strategies.monthly_etf import MonthlyEtfStrategy

CODE_PATHS = (
    "src/quant/data/publish_cross_asset_etfs.py", "src/quant/data/refresh_etf_prices.py",
    "src/quant/research/monthly_etf.py", "src/quant/strategies/monthly_etf.py",
    "src/quant/research/classic_monthly_baseline.py", "src/quant/research/run_s1_walk_forward.py",
    "src/quant/backtest/daily_account.py", "src/quant/backtest/daily_simulator.py",
    "src/quant/backtest/rules.py", "src/quant/backtest/costs.py",
    "src/quant/data/etf_paper_inputs.py", "src/quant/data/etf_research_inputs.py",
)


def read_inputs(data_root: Path, candidates: tuple[str, ...], data: dict[str, Any]) -> tuple[
    pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame,
]:
    if "cross_asset_snapshot" not in data:
        bars, prices, calendar, instruments = read_etf_research_inputs(
            data_root, list(candidates), data["start"], data["end"])
        return bars, prices, calendar, instruments, read_etf_dividends(data_root, list(candidates), data["start"])
    frames = read_cross_asset_etfs(data_root, data["cross_asset_snapshot"])
    calendar = frames["calendar"]
    selected = []
    for label in ("bars", "prices"):
        frame = frames[label].filter(pl.col("symbol").is_in(list(candidates))
            & pl.col("trade_date").is_between(data["start"], data["end"]))
        for symbol in candidates:
            expected = calendar.filter((pl.col("market") == symbol[-2:]) & pl.col("is_open")
                & pl.col("date").is_between(data["start"], data["end"]))["date"].to_list()
            observed = frame.filter(pl.col("symbol") == symbol)["trade_date"].to_list()
            if not expected or len(observed) != len(expected) or set(observed) != set(expected):
                raise ValueError(f"Incomplete cross-asset {label}: {symbol}")
        selected.append(frame)
    instruments = frames["instruments"].filter(pl.col("symbol").is_in(list(candidates)))
    if instruments.height != len(candidates) or set(instruments["symbol"]) != set(candidates):
        raise ValueError("Missing cross-asset instruments")
    dividends = frames["dividends"].filter(pl.col("symbol").is_in(list(candidates))
        & (pl.col("ex_date") >= data["start"]))
    return selected[0], selected[1], calendar, instruments, dividends


def completed_month_prices(prices: pl.DataFrame, calendar: pl.DataFrame) -> pl.DataFrame:
    """Use known exchange month ends; an unfinished month is never a monthly bar."""
    ends = calendar.filter((pl.col("market") == "SH") & pl.col("is_open")).with_columns(
        pl.col("date").dt.strftime("%Y-%m").alias("month")).group_by("month").agg(pl.col("date").max())
    return prices.filter(pl.col("trade_date").is_in(ends["date"].implode())).sort("trade_date", "symbol")


def monthly_targets(
    prices: pl.DataFrame, calendar: pl.DataFrame, *, start: dt.date, end: dt.date,
    candidates: tuple[str, ...], name: str, strategy: MonthlyEtfStrategy | None,
) -> pl.DataFrame:
    sessions = calendar.filter((pl.col("market") == "SH") & pl.col("is_open"))["date"].sort().to_list()
    pairs = [(prior, day) for prior, day in zip(sessions, sessions[1:])
             if start <= day <= end and (prior < start or prior.month != day.month)]
    monthly = completed_month_prices(prices, calendar)
    frames = []
    for as_of, execution in pairs:
        if strategy is not None:
            target = strategy.target_weights(as_of, monthly)
        else:
            target = pl.DataFrame({"as_of": [as_of] * len(candidates), "symbol": candidates,
                "strategy": [name] * len(candidates), "strategy_version": ["v1"] * len(candidates),
                "weight": [1 / len(candidates)] * len(candidates)})
        frames.append(target.with_columns(pl.lit(execution).alias("execution_date")))
    if not frames:
        raise ValueError("No monthly execution dates")
    return pl.concat(frames).sort("execution_date", "symbol")


def admission_checks(results: list[dict[str, Any]], settings: dict[str, Any]) -> dict[str, bool]:
    one = [r for r in results if r["comparison"] == "strategy" and r["cost_multiplier"] == 1.]
    two = [r for r in results if r["comparison"] == "strategy" and r["cost_multiplier"] == 2.]
    baseline = {r["fold"]: r for r in results if r["comparison"] == "s0" and r["cost_multiplier"] == 1.}
    def calmar(row: dict[str, Any]) -> float:
        return row["cagr"] / max(abs(row["max_drawdown"]), 1e-12)
    forward = next(r for r in one if r["test_start"] == str(settings["forward_start"]))
    return {
        "all_1x_folds_positive": all(r["total_return"] > 0 for r in one),
        "enough_2x_folds_positive": sum(r["total_return"] > 0 for r in two) / len(two)
            >= settings["minimum_2x_positive_fold_fraction"],
        "all_folds_better_drawdown_or_calmar": all(
            r["max_drawdown"] > baseline[r["fold"]]["max_drawdown"] or calmar(r) > calmar(baseline[r["fold"]]) for r in one),
        "turnover_within_limit": all(r["annualized_one_way_turnover"] <= settings["maximum_annualized_one_way_turnover"] for r in one),
        "forward_shortfall_within_limit": forward["total_return"] >= baseline[forward["fold"]]["total_return"]
            - settings["forward_maximum_shortfall_to_s0"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    args = parser.parse_args()
    project = Path.cwd().resolve()
    config = tomllib.loads(args.config.read_text(encoding="utf-8"))
    spec, data, portfolio = config["research"], config["data"], config["portfolio"]
    candidates = tuple(sorted(config["universe"]["symbols"]))
    bars, prices, calendar, instruments, dividends = read_inputs(args.data_root, candidates, data)
    folds = tuple(ResearchFoldV1(fold=i + 1, **row) for i, row in enumerate(config["walk_forward"]["folds"]))
    if any(a.test_end >= b.test_start for a, b in zip(folds, folds[1:])):
        raise ValueError("Test folds must be disjoint")
    definition = config["strategy"]
    strategy = MonthlyEtfStrategy(candidates, definition["kind"], definition["lookback_months"],
        definition["skip_months"], definition["top_k"], name=spec["strategy_name"],
        absolute_momentum_filter=definition.get("absolute_momentum_filter", False))
    results: list[dict[str, Any]] = []
    validations: list[dict[str, Any]] = []
    targets_out: list[pl.DataFrame] = []
    navs: list[pl.DataFrame] = []
    trades_out: list[pl.DataFrame] = []
    rejects_out: list[pl.DataFrame] = []
    for fold in folds:
        for label, start, end, multiples in (
            ("validation", fold.validation_start, fold.validation_end, [1.]),
            ("test", fold.test_start, fold.test_end, portfolio["cost_multipliers"]),
        ):
            targets_by_comparison = {comparison: monthly_targets(prices, calendar, start=start, end=end,
                candidates=candidates, name=spec["strategy_name"] if comparison == "strategy" else "s0_monthly",
                strategy=strategy if comparison == "strategy" else None) for comparison in ("strategy", "s0")}
            sessions = calendar.filter((pl.col("market") == "SH") & pl.col("is_open")
                & pl.col("date").is_between(start, end))["date"].sort().to_list()
            for comparison, targets in targets_by_comparison.items():
                targets_out.append(targets.with_columns(pl.lit(fold.fold).alias("fold"), pl.lit(label).alias("period"),
                                                        pl.lit(comparison).alias("comparison")))
            for multiplier in multiples:
                scenario = copy.deepcopy(config)
                for key in ("commission_rate", "commission_min", "slippage", "slippage_per_share"):
                    scenario["costs"]["etf"][key] *= multiplier
                states = etf_session_states(bars, dividends, slippage=scenario["costs"]["etf"]["slippage"],
                    slippage_per_share=scenario["costs"]["etf"]["slippage_per_share"])
                for comparison, targets in targets_by_comparison.items():
                    nav, trades, rejects = replay(bars=bars, calendar=calendar, instruments=instruments,
                        targets=targets, dividends=dividends, market_states=states, config=scenario,
                        sessions=sessions, name=spec["strategy_name"] if comparison == "strategy" else "s0_monthly")
                    score = metrics(nav, trades, initial_cash=portfolio["initial_cash"])
                    score.pop("target_gap_count", None)
                    score.pop("absolute_target_gap_notional", None)
                    row = {"fold": fold.fold, "comparison": comparison, "cost_multiplier": multiplier,
                           "test_start": str(start), "test_end": str(end), "sessions": len(sessions), **score}
                    (results if label == "test" else validations).append(row)
                    for collection, frame in ((navs, nav), (trades_out, trades), (rejects_out, rejects)):
                        collection.append(frame.with_columns(pl.lit(fold.fold).alias("fold"), pl.lit(label).alias("period"),
                            pl.lit(comparison).alias("comparison"), pl.lit(multiplier).alias("cost_multiplier")))
                print(f"Completed {label} fold {fold.fold}, {multiplier:g}x", flush=True)
    checks = admission_checks(results, config["admission"])
    conclusion: Literal["PAPER_CANDIDATE", "REJECTED"] = "PAPER_CANDIDATE" if all(checks.values()) else "REJECTED"
    report = {"hypothesis_id": spec["hypothesis_id"], "conclusion": conclusion, "admission": checks,
        "results": results, "validation_results": validations, "parameters": definition,
        "caveat": "The fixed ETF pool is retrospective; results require confirmation in forward paper trading."}
    outputs = {"report.json": canonical_json_bytes(report), "config.toml": args.config.read_bytes()}
    for name, frames in (("nav", navs), ("trades", trades_out), ("rejections", rejects_out), ("targets", targets_out)):
        buffer = io.BytesIO()
        pl.concat(frames, how="diagonal_relaxed").write_parquet(buffer)
        outputs[f"{name}.parquet"] = buffer.getvalue()
    aggregate = []
    for comparison in ("strategy", "s0"):
        for multiplier in portfolio["cost_multipliers"]:
            value = math.prod(1 + r["total_return"] for r in results
                             if r["comparison"] == comparison and r["cost_multiplier"] == multiplier) - 1
            aggregate.append((f"{comparison}_return_{multiplier:g}x", value))
    run = LightweightResearchRunV1(schema_version="lightweight-research-run-v1", run_id="",
        hypothesis_id=spec["hypothesis_id"], hypothesis=spec["hypothesis"], strategy_name=spec["strategy_name"],
        strategy_version=spec["strategy_version"], conclusion=conclusion, random_seed=spec["random_seed"],
        config_relative_path=args.config.resolve().relative_to(project).as_posix(),
        config_sha256=hashlib.sha256(args.config.read_bytes()).hexdigest(),
        code_sha256=compute_code_sha256(project_root=project, relative_paths=CODE_PATHS),
        universe_name=config["universe"]["name"], universe_frozen_as_of=config["universe"]["frozen_as_of"],
        candidate_symbols=candidates, data_start=data["start"], data_end=data["end"],
        signal_timing="close", execution_timing="next_session_open", valuation_timing="close",
        folds=folds, cost_multipliers=tuple(portfolio["cost_multipliers"]), selection_metric="literature_fixed",
        inputs=tuple(sorted((dataframe_input_digest(name=name, frame=frame, sort_by=sort, date_column=date)
            for name, frame, sort, date in (("bars", bars, ("trade_date", "symbol"), "trade_date"),
                ("prices", prices, ("trade_date", "symbol"), "trade_date"),
                ("calendar", calendar, ("date", "market"), "date"),
                ("instruments", instruments, ("symbol",), "list_date"),
                ("dividends", dividends, ("ex_date", "symbol"), "ex_date"))), key=lambda item: item.name)),
        outputs=(), aggregate_metrics=tuple(sorted(aggregate)), caveats=(report["caveat"],))
    output, completed, reused = publish_lightweight_research_run(artifact_root=project / "artifacts", run=run, output_payloads=outputs)
    print(json.dumps({"output": str(output), "conclusion": completed.conclusion, "reused": reused, "admission": checks}))


if __name__ == "__main__":
    main()
