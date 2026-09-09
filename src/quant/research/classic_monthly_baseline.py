"""Monthly z-score baseline implementation used by the existing composite CLI."""

import copy
import datetime as dt
import hashlib
import io
import json
import math
from pathlib import Path
from typing import Any, Literal

import polars as pl

from quant.backtest.daily_account import advance
from quant.data.etf_paper_inputs import etf_session_states, read_etf_dividends
from quant.data.etf_research_inputs import read_etf_research_inputs
from quant.data.refresh_stocks import read_stock_data
from quant.data.stock_name_history import read_name_history
from quant.data.stock_execution_inputs import prepare_stock_execution_inputs, stock_session_states
from quant.factors import compute_classic_daily_factors
from quant.factors.reversal_volatility import compute_reversal_volatility_factors, exclude_historical_risk_names
from quant.research.classic_factor_composite import (
    build_equal_weight_zscore_composite, build_monthly_zscore_targets,
)
from quant.research.classic_factor_evaluation import evaluate_factor_period, evaluate_factor_redundancy
from quant.research.factor_labels import build_next_open_factor_labels
from quant.research.lightweight_run import (
    LightweightResearchRunV1, ResearchFoldV1, ResearchInputDigestV1, canonical_json_bytes, compute_code_sha256,
    dataframe_input_digest, publish_lightweight_research_run,
)
from quant.research.run_classic_factors import select_frozen_liquid_universe
from quant.research.run_s1_walk_forward import metrics

CODE_PATHS = (
    "src/quant/factors/earnings_surprise.py",
    "src/quant/research/monthly_sue.py",
    "src/quant/research/monthly_intraday_factors.py",
    "src/quant/data/stock_intraday_repository.py",
    "src/quant/factors/intraday_low_frequency.py",
    "src/quant/research/run_classic_factor_composite.py",
    "src/quant/research/classic_monthly_baseline.py",
    "src/quant/research/classic_factor_composite.py",
    "src/quant/research/run_classic_factors.py",
    "src/quant/research/run_s1_walk_forward.py",
    "src/quant/factors/classic.py",
    "src/quant/factors/reversal_volatility.py",
    "src/quant/data/stock_name_history.py",
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
    "src/quant/research/monthly_financial_factors.py",
    "src/quant/research/pit_quality_research.py",
    "src/quant/data/financial_repository.py",
    "src/quant/data/financial_pit.py",
    "src/quant/data/financial_clean.py",
    "src/quant/factors/pit_quality.py",
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
        writeoff = 0.0
        removed = []
        if config["portfolio"].get("delisted_holding_recovery") == 0.0:
            delisted = instruments.filter(pl.col("delist_date") < date)["symbol"].to_list()
            for symbol in delisted:
                holding = state["holdings"].pop(symbol, None)
                if holding is not None:
                    writeoff += holding["quantity"] * holding["mark_price"]
                    removed.append(symbol)
            state["restricted_shares"] = [r for r in state.get("restricted_shares", [])
                                           if r["symbol"] not in removed]
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
        try:
            state, result = advance(
                date=date, state=state, bars=today_bars, calendar=calendar,
                instruments=instruments, market_states=market_states, dividends=dividends,
                config=account_config,
            )
        except ValueError as exc:
            relevant = set(state["holdings"]) | (set(batch["symbol"]) if batch is not None else set())
            inactive = instruments.filter(pl.col("symbol").is_in(relevant) & (
                (pl.col("list_date") > date) | (pl.col("delist_date") < date)))
            raise ValueError(f"{exc}; session={date}; inactive={inactive.select('symbol', 'delist_date').to_dicts()}") from exc
        state["nav"][-1]["position_count"] = len(state["holdings"])
        state["nav"][-1]["delisting_writeoff"] = writeoff
        state["nav"][-1]["delisted_symbols"] = ",".join(sorted(removed))
        state["nav"][-1]["missing_target_positions"] = (
            len(set(batch.filter(pl.col("weight") > 0).get_column("symbol")) - set(state["holdings"]))
            if batch is not None else None
        )
        trades.append(result.trades)
        rejections.append(result.rejections)
    return (pl.DataFrame(state["nav"]).with_columns(pl.col("date").str.to_date()),
            pl.concat(trades, how="vertical_relaxed"), pl.concat(rejections, how="vertical_relaxed"))


def meets_portfolio_candidate(results: list[dict[str, Any]], admission: dict[str, Any]) -> bool:
    """Apply the roadmap's return, cost, turnover and drawdown rules to each fold."""
    one = [row for row in results if row["comparison"] == "top50" and row["cost_multiplier"] == 1]
    by_key = {(row["fold"], row["comparison"], row["cost_multiplier"]): row for row in results}
    if not one:
        return False
    for row in one:
        benchmark = by_key.get((row["fold"], "510300", 1))
        double = by_key.get((row["fold"], "top50", 2))
        if benchmark is None or double is None:
            return False
        if not (row["cagr"] - benchmark["cagr"] >= admission["minimum_annual_excess_1x"]
                and double["total_return"] > 0
                and row["annualized_one_way_turnover"] <= admission["maximum_annual_one_way_turnover"]
                and -row["max_drawdown"] <= -benchmark["max_drawdown"] * admission["maximum_drawdown_ratio_to_benchmark"]):
            return False
    return True


def run_baseline(
    *, config: dict[str, Any], config_path: Path, project_root: Path,
    data_root: Path, artifact_root: Path,
) -> int:
    data, universe, portfolio = config["data"], config["universe"], config["portfolio"]
    if config.get("financials", {}).get("factor_family") == "sue8":
        expected_sue = {
            "formula": "(delta_q - mean(delta_q-1..delta_q-8)) / std(delta_q-1..delta_q-8)",
            "quarter_value": "single_quarter_n_income_attr_p",
            "seasonal_difference_lag": 4, "prior_window": 8,
            "standard_deviation_ddof": 1, "missing_quarter": "null",
            "zero_standard_deviation": "null",
        }
        if any(config.get("sue", {}).get(k) != v for k, v in expected_sue.items()):
            raise ValueError("Unsupported SUE formula configuration")
    if (not config["walk_forward"]["folds"]
        or config["composite"]["standard_deviation_ddof"] != 0
        or config["composite"]["winsorization"] != "none"
        or len(config["factors"]["names"]) != len(config["factors"]["directions"])
        or portfolio["cost_multipliers"] != [0.5, 1.0, 2.0]):
        raise ValueError("Unsupported monthly baseline configuration")
    folds = [ResearchFoldV1(index, **fold) for index, fold in enumerate(config["walk_forward"]["folds"], 1)]
    start, end = min(f.test_start for f in folds), max(f.test_end for f in folds)
    if any(a.test_end >= b.test_start for a, b in zip(folds, folds[1:])):
        raise ValueError("Test folds must be chronological and disjoint")
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
    factors = compute_classic_daily_factors(bars)
    extra_inputs: list[tuple[str, pl.DataFrame, tuple[str, ...], str]] = []
    extra_outputs: list[tuple[str, pl.DataFrame]] = []
    extra_digests: list[ResearchInputDigestV1] = []
    if "intraday" in config:
        from quant.research.monthly_intraday_factors import read_monthly_intraday_factors

        intraday, minute_digest = read_monthly_intraday_factors(
            data_root=data_root, settings=config["intraday"], candidates=candidates,
            sessions=all_sessions, start=data["warmup_start"], end=end, daily_bars=bars,
        )
        factors = factors.join(intraday, on=["symbol", "trade_date"], how="left", validate="1:1")
        extra_digests.append(minute_digest)
        extra_outputs.append(("intraday_factors", intraday))
        print(f"Computed minute factors from {minute_digest.rows} bars", flush=True)
    if "financials" in config:
        from quant.research.monthly_financial_factors import read_monthly_financial_factors

        financial, histories = read_monthly_financial_factors(
            data_root=data_root, settings=config["financials"], candidates=candidates,
            sessions=all_sessions, start=data["research_start"], end=end,
        )
        factors = factors.join(financial.factors, on=["symbol", "trade_date"], how="inner", validate="1:1")
        required = config["financials"].get("ranking_requires_factors", [])
        if required:
            factors = factors.filter(pl.all_horizontal(pl.col(name).is_finite() for name in required))
        extra_inputs.extend((f"financial-{name}", frame,
                             ("symbol", "end_date", "available_date", "report_type", "comp_type"),
                             "available_date") for name, frame in histories.items())
        extra_outputs.extend((("financial_factors", financial.factors),
                              ("financial_eligibility", financial.eligibility),
                              ("financial_quarantined", financial.quarantined)))
        print(f"Computed {financial.factors['trade_date'].n_unique()} monthly PIT cross-sections", flush=True)
    if "b3" in config:
        basic = read_stock_data(data_root=data_root, config=refresh_config, table="daily_basic",
                                start=data["warmup_start"], end=end, symbols=list(candidates))
        new_factors, proxy_returns = compute_reversal_volatility_factors(
            bars, basic, sessions=all_sessions, settings=config["b3"])
        factors = factors.join(new_factors, on=["symbol", "trade_date"], how="left", validate="1:1")
        extra_inputs.append(("daily-basic", basic, ("trade_date", "symbol"), "trade_date"))
        extra_outputs.append(("proxy_returns", proxy_returns))
        print("Computed fixed reversal/volatility factors", flush=True)
    directions = tuple(zip(config["factors"]["names"], config["factors"]["directions"]))
    eligible = factors.filter((pl.col("history_rows") >= config["factors"]["minimum_history_rows"])
                              & (pl.col("liquidity_20") >= universe["minimum_average_amount"]))
    if config.get("eligibility", {}).get("historical_exchange_name"):
        names = read_name_history(data_root, list(candidates), end)
        eligible = exclude_historical_risk_names(eligible, names)
        extra_inputs.append(("name-history", names, ("symbol", "start_date", "name"), "start_date"))
    scored = build_equal_weight_zscore_composite(eligible, component_directions=directions)
    targets = pl.concat([build_monthly_zscore_targets(
        scored, sessions=all_sessions, start=fold.test_start, end=fold.test_end, top_k=portfolio["top_k"],
        strategy_name=config["research"]["strategy_name"],
        retention_rank=portfolio.get("retention_rank"),
    ).with_columns(pl.lit(fold.fold).alias("fold")) for fold in folds])
    selected = sorted(targets.get_column("symbol").unique().to_list())
    execution_dates = sorted(targets.get_column("execution_date").unique().to_list())
    limits, suspensions, dividends, instruments = prepare_stock_execution_inputs(
        data_root=data_root, symbols=selected, execution_dates=execution_dates, start=start, end=end,
        output=data_root / "clean/stock_execution" / config["research"]["hypothesis_id"],
    )
    dividends = dividends.with_columns((pl.col("div_cash") * (1 - portfolio["stock_dividend_withholding"])).alias("div_cash"))
    benchmark_dividends = read_etf_dividends(data_root, [portfolio["benchmark"]], start)
    benchmark_name = "510300_buy_hold"
    benchmark_targets = pl.concat([pl.DataFrame({
        "as_of": [max(date for date in all_sessions if date < fold.test_start)],
        "execution_date": [min(date for date in all_sessions if fold.test_start <= date <= fold.test_end)],
        "symbol": [portfolio["benchmark"]], "strategy": [benchmark_name],
        "strategy_version": ["v1"], "weight": [1.0], "fold": [fold.fold],
    }) for fold in folds])
    stock_bars = bars.filter(pl.col("symbol").is_in(selected))
    results: list[dict[str, Any]] = []
    navs: list[pl.DataFrame] = []
    trades: list[pl.DataFrame] = []
    rejects: list[pl.DataFrame] = []
    for fold in folds:
        sessions = [date for date in all_sessions if fold.test_start <= date <= fold.test_end]
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
                ("top50", stock_bars, instruments, targets.filter(pl.col("fold") == fold.fold).drop("fold"), dividends, stock_states, config["research"]["strategy_name"]),
                ("510300", benchmark_bars, benchmark_instruments, benchmark_targets.filter(pl.col("fold") == fold.fold).drop("fold"), benchmark_dividends, benchmark_states, benchmark_name),
            ):
                nav, fills, rejected = replay(bars=bar_data, calendar=calendar, instruments=master,
                    targets=weights, dividends=events, market_states=states, config=scenario,
                    sessions=sessions, name=name)
                scores = metrics(nav, fills, initial_cash=portfolio["initial_cash"])
                # The shared metric helper's optional gap diagnostics were not requested here.
                scores.pop("target_gap_count", None)
                scores.pop("absolute_target_gap_notional", None)
                results.append({"fold": fold.fold, "comparison": comparison, "cost_multiplier": multiplier,
                                "rejected_orders": rejected.height,
                                "average_position_count": nav.get_column("position_count").mean(),
                                "minimum_position_count": nav.get_column("position_count").min(),
                                "maximum_missing_targets_on_rebalance": nav.get_column("missing_target_positions").max(),
                                **scores})
                for collection, frame in ((navs, nav), (trades, fills), (rejects, rejected)):
                    collection.append(frame.with_columns(pl.lit(fold.fold).alias("fold"), pl.lit(comparison).alias("comparison"),
                                                         pl.lit(multiplier).alias("cost_multiplier")))
                print(f"Completed fold {fold.fold} {comparison} cost {multiplier}x", flush=True)
    # Direction diagnostics do not select or alter the already frozen component weights.
    panel = build_next_open_factor_labels(factor_values=scored, bars=bars,
                                          sessions=all_sessions, horizons=(20,))
    diagnostic_rows: list[dict[str, Any]] = []
    daily_diagnostics: list[pl.DataFrame] = []
    group_diagnostics: list[pl.DataFrame] = []
    redundancy_rows: list[dict[str, Any]] = []
    for fold in folds:
        for label, period_start, period_end in (
            ("train", fold.train_start, fold.train_end),
            ("validation", fold.validation_start, fold.validation_end),
            ("test", fold.test_start, fold.test_end),
        ):
            for factor, direction in (directions if "b3" in config else (*directions, ("equal_zscore", 1))):
                daily, groups, score = evaluate_factor_period(panel, factor=factor, horizon=20,
                    start_date=period_start, end_date=period_end,
                    minimum_symbols=config["factors"]["minimum_daily_symbols"], direction=direction)
                means = groups.group_by("group").agg(pl.col("mean_return").mean()).sort("group")
                diagnostic_rows.append({"fold": fold.fold, "period": label, "factor": factor,
                    "direction": direction, "group_mean_returns": means["mean_return"].to_list(),
                    "group_monotonicity": means.select(pl.corr("group", "mean_return", method="spearman")).item(), **score})
                for collection, frame in ((daily_diagnostics, daily), (group_diagnostics, groups)):
                    collection.append(frame.with_columns(pl.lit(fold.fold).alias("fold"),
                        pl.lit(label).alias("period"), pl.lit(factor).alias("factor")))
        if "redundancy_references" in config["admission"]:
            _, redundancy = evaluate_factor_redundancy(scored, factors=tuple(name for name, _ in directions),
                reference_factors=tuple(config["admission"]["redundancy_references"]),
                start_date=fold.test_start, end_date=fold.test_end,
                minimum_symbols=config["factors"]["minimum_daily_symbols"])
            redundancy_rows.extend(redundancy.with_columns(pl.lit(fold.fold).alias("fold")).to_dicts())
    def compounded(comparison: str, multiplier: float) -> float:
        return math.prod(1 + row["total_return"] for row in results
                         if row["comparison"] == comparison and row["cost_multiplier"] == multiplier) - 1
    one_return, two_return = compounded("top50", 1.0), compounded("top50", 2.0)
    excess = one_return - compounded("510300", 1.0)
    passed = one_return > 0 and two_return > 0 and excess > 0
    if "minimum_mean_test_rank_ic" in config["admission"]:
        primary = [r for r in diagnostic_rows if r["period"] == "test" and r["factor"] == directions[0][0]]
        passed = (sum(r["rank_ic_mean"] for r in primary) / len(primary) >= config["admission"]["minimum_mean_test_rank_ic"]
                  and sum(r["rank_ic_mean"] > 0 for r in primary) >= config["admission"]["minimum_positive_test_folds"]
                  and max(r["median_abs_rank_corr"] for r in redundancy_rows)
                  < config["admission"]["maximum_absolute_rank_correlation"])
    conclusion: Literal["RESEARCH_ONLY", "REJECTED", "PAPER_CANDIDATE"] = "RESEARCH_ONLY" if passed else "REJECTED"
    if (config["admission"].get("maximum_conclusion") == "PAPER_CANDIDATE"
        and meets_portfolio_candidate(results, config["admission"])):
        conclusion = "PAPER_CANDIDATE"
    caveat = (
        "Monthly PIT replication using a fixed historical financial snapshot; financial freshness varies by issuer."
        if "financials" in config else
        "Historical replication within a fixed liquid universe; the IVOL regressors are local size/value proxies."
        if "b3" in config else
        "Five-minute historical replication in the frozen liquid pool; incomplete sessions invalidate the rolling factors."
        if "intraday" in config else
        "The component selection used earlier research; this is an exploratory baseline."
    )
    report = {"hypothesis_id": config["research"]["hypothesis_id"], "conclusion": conclusion,
              "period": [str(start), str(end)], "sessions": sum(sum(f.test_start <= date <= f.test_end for date in all_sessions) for f in folds), "universe": len(candidates),
              "selected_symbols": len(selected), "rebalance_count": len(execution_dates),
              "results": results, "factor_diagnostics": diagnostic_rows, "redundancy": redundancy_rows, "excess_return_1x": excess,
              "dividend_withholding_assumption": portfolio["stock_dividend_withholding"],
              "caveat": caveat}
    outputs = {"report.json": canonical_json_bytes(report)}
    for name, frame in (("nav", pl.concat(navs, how="vertical_relaxed")),
                        ("trades", pl.concat(trades, how="vertical_relaxed")),
                        ("rejections", pl.concat(rejects, how="vertical_relaxed")),
                        ("targets", targets), ("benchmark_targets", benchmark_targets),
                        ("daily_ic", pl.concat(daily_diagnostics)), ("groups", pl.concat(group_diagnostics)),
                        *extra_outputs):
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
        folds=tuple(folds), cost_multipliers=tuple(portfolio["cost_multipliers"]),
        selection_metric="fixed_equal_zscore",
        inputs=tuple(sorted([*extra_digests, *(dataframe_input_digest(name=name, frame=frame, sort_by=sort, date_column=date)
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
                         *extra_inputs,
                     ))], key=lambda item: item.name)), outputs=(), aggregate_metrics=(
                         ("excess_return_1x", excess), ("net_return_1x", one_return),
                         ("net_return_2x", two_return)),
        caveats=(report["caveat"],),
    )
    output, completed, reused = publish_lightweight_research_run(artifact_root=artifact_root, run=run, output_payloads=outputs)
    print(json.dumps({"output": str(output), "run_id": completed.run_id, "reused": reused,
                      "conclusion": conclusion, "results": results}, ensure_ascii=False))
    return 0
