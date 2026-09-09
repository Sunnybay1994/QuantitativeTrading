"""09:30 versus 09:35 execution of frozen monthly weights through the daily account."""

import argparse
import copy
import json
import tomllib
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.etf_execution_quotes import execution_bars, quote_quality_errors, read_execution_quotes
from quant.data.etf_limits import read_limits
from quant.data.etf_paper_inputs import etf_session_states
from quant.research.classic_monthly_baseline import replay
from quant.research.monthly_etf import monthly_targets, read_inputs
from quant.research.run_s1_walk_forward import metrics
from quant.strategies.inverse_volatility import InverseVolatilityStrategy


def compare_test_results(rows: list[dict[str, Any]]) -> dict[str, Any]:
    test = {(r["allocation"], r["time"], r["cost_multiplier"]): r for r in rows if r["period"] == "test"}
    comparisons = []
    for allocation in ("inverse_volatility", "equal_weight"):
        for cost in (.5, 1., 2.):
            first, later = test[(allocation, "09:30", cost)], test[(allocation, "09:35", cost)]
            comparisons.append({"allocation": allocation, "cost_multiplier": cost,
                "return_increment": later["total_return"] - first["total_return"],
                "drawdown_increment": later["max_drawdown"] - first["max_drawdown"]})
    passed = all(r["return_increment"] > 0 and r["drawdown_increment"] >= 0 for r in comparisons)
    return {"comparisons": comparisons, "conclusion": "RESEARCH_ONLY" if passed else "REJECTED"}


def run(config_path: Path, data_root: Path, output: Path) -> dict[str, Any]:
    payload = config_path.read_bytes()
    config = tomllib.loads(payload.decode("utf-8"))
    definition = config["execution"]
    if (definition["source"] != "yahoo" or definition["frequency"] != "5m"
        or definition["baseline_time"] != "09:30" or definition["alternative_time"] != "09:35"
        or definition["cost_multipliers"] != [.5, 1., 2.]
        or definition["allocations"] != ["inverse_volatility", "equal_weight"]
        or definition["missing_quote"] != "fail"):
        raise ValueError("Unsupported execution study")
    baseline_payload = Path(config["research"]["baseline_config"]).read_bytes()
    baseline = tomllib.loads(baseline_payload.decode("utf-8"))
    symbols = tuple(sorted(baseline["universe"]["symbols"]))
    bars, prices, calendar, instruments, dividends = read_inputs(data_root, symbols, baseline["data"])
    strategy = InverseVolatilityStrategy(symbols, baseline["strategy"]["lookback_sessions"], name="b22_fixed")
    batches = {}
    for period in ("train", "validation", "test"):
        start, end = config["split"][f"{period}_start"], config["split"][f"{period}_end"]
        for allocation in definition["allocations"]:
            batches[(period, allocation)] = monthly_targets(prices, calendar, start=start, end=end,
                candidates=symbols, name="b22_fixed", strategy=strategy if allocation == "inverse_volatility" else None)
    dates = sorted({day for batch in batches.values() for day in batch["execution_date"].to_list()})
    quotes = read_execution_quotes(data_root, symbols, dates)
    limits = read_limits(data_root)
    output.mkdir(parents=True, exist_ok=False)
    (output / "config.toml").write_bytes(payload)
    (output / "baseline_config.toml").write_bytes(baseline_payload)
    quotes.write_parquet(output / "quotes.parquet")
    errors = quote_quality_errors(quotes)
    if errors:
        result = {"hypothesis_id": config["research"]["hypothesis_id"], "conclusion": "REJECTED",
                  "reason": "execution_data_unusable_for_paired_comparison", "data_errors": errors,
                  "results": [], "comparisons": [], "historical_baseline_conclusion": "REJECTED"}
        (output / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
    rows: list[dict[str, Any]] = []
    navs: list[pl.DataFrame] = []
    trades_out: list[pl.DataFrame] = []
    rejects_out: list[pl.DataFrame] = []
    targets_out: list[pl.DataFrame] = []
    for period in ("train", "validation", "test"):
        start, end = config["split"][f"{period}_start"], config["split"][f"{period}_end"]
        sessions = calendar.filter((pl.col("market") == "SH") & pl.col("is_open")
            & pl.col("date").is_between(start, end))["date"].sort().to_list()
        period_bars = bars.filter(pl.col("trade_date").is_between(start, end))
        for allocation in definition["allocations"]:
            targets = batches[(period, allocation)]
            targets_out.append(targets.with_columns(pl.lit(period).alias("period"), pl.lit(allocation).alias("allocation")))
            for multiplier in definition["cost_multipliers"]:
                scenario = copy.deepcopy(baseline)
                for key in ("commission_rate", "commission_min", "slippage", "slippage_per_share"):
                    scenario["costs"]["etf"][key] *= multiplier
                for time in ("09:30", "09:35"):
                    observed = execution_bars(period_bars, quotes, time, definition["price_range_tolerance"])
                    states = etf_session_states(observed, dividends, official_limits=limits,
                        slippage=scenario["costs"]["etf"]["slippage"],
                        slippage_per_share=scenario["costs"]["etf"]["slippage_per_share"])
                    nav, trades, rejects = replay(bars=observed, calendar=calendar, instruments=instruments,
                        targets=targets, dividends=dividends, market_states=states, config=scenario,
                        sessions=sessions, name="b22_fixed")
                    label = {"period": period, "allocation": allocation, "time": time, "cost_multiplier": multiplier}
                    rows.append({**label, "sessions": len(sessions),
                        "rebalance_dates": targets["execution_date"].n_unique(),
                        **metrics(nav, trades, initial_cash=baseline["portfolio"]["initial_cash"])})
                    for collection, frame in ((navs, nav), (trades_out, trades), (rejects_out, rejects)):
                        collection.append(frame.with_columns([pl.lit(v).alias(k) for k, v in label.items()]))
        print(f"Completed {period}", flush=True)
    result = {"hypothesis_id": config["research"]["hypothesis_id"], "results": rows,
              "historical_baseline_conclusion": "REJECTED", **compare_test_results(rows)}
    for name, frames in (("nav", navs), ("trades", trades_out), ("rejections", rejects_out), ("targets", targets_out)):
        pl.concat(frames, how="diagonal_relaxed").write_parquet(output / f"{name}.parquet")
    (output / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    args = parser.parse_args()
    result = run(args.config, args.data_root, args.output)
    print(json.dumps({k: v for k, v in result.items() if k != "results"}))


if __name__ == "__main__":
    main()
