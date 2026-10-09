"""Diagnose the fixed five-factor value family from saved accounts, without replay."""
from __future__ import annotations

import argparse
import datetime as dt
from itertools import combinations
from pathlib import Path
import tomllib

import numpy as np
import polars as pl

from quant.reporting.cycle_stress import path_statistics
from quant.research.value_family_evidence import Evidence, annual_security_bridge, read_account, returns, save, write_json


def performance(account: dict, start: dt.date, end: dt.date) -> dict:
    nav, tr = account["nav"], account["trades"]
    daily = returns(nav, start, end)
    if daily.is_empty() or daily["date"][0] != start or daily["date"][-1] != end:
        raise ValueError("Incomplete account window")
    risk = path_statistics(nav, start=start, end=end)
    tr = tr.filter(pl.col("date").is_between(start, end))
    traded = tr.group_by("date").agg(pl.col("notional").sum(), pl.col("fee").sum(), pl.col("slippage_cost").sum())
    cost = daily.select("date", "prior_equity").join(traded, on="date", how="left").fill_null(0.)
    prior = nav.filter(pl.col("date") < start)
    fee_start = prior["cumulative_fees"][-1] if prior.height else 0.
    fee_change = daily["cumulative_fees"][-1] - fee_start
    fee_error = fee_change - tr["fee"].sum()
    if abs(fee_error) > 1e-5:
        raise ValueError(f"Fee ledger differs from NAV: {fee_error}")
    return {**account["identity"], **risk,
        "annual_turnover": cost.select((pl.col("notional") / pl.col("prior_equity") / 2).sum()).item() * 252 / daily.height,
        "fee_cash_cny": tr["fee"].sum(), "slippage_cash_cny": tr["slippage_cost"].sum(),
        "annual_fee_on_nav": cost.select((pl.col("fee") / pl.col("prior_equity")).sum()).item() * 252 / daily.height,
        "annual_slippage_on_nav": cost.select((pl.col("slippage_cost") / pl.col("prior_equity")).sum()).item() * 252 / daily.height,
        "fee_reconciliation_error": fee_error,
        "mean_invested_fraction": daily.select((pl.col("market_value") / pl.col("equity")).mean()).item(),
        "median_position_count": daily["position_count"].median(),
        "maximum_position_count": daily["position_count"].max(),
        "trade_count": tr.height, "delisting_writeoff_cny": daily["delisting_writeoff"].sum()}


def common_pair(a: dict, b: dict, start: dt.date, end: dt.date) -> dict:
    active_a = a["nav"].filter(pl.col("market_value") > 0)
    active_b = b["nav"].filter(pl.col("market_value") > 0)
    first = max(start, active_a["date"].min(), active_b["date"].min())
    last = min(end, a["nav"]["date"].max(), b["nav"]["date"].max())
    left, right = returns(a["nav"], first, last), returns(b["nav"], first, last)
    if not left["date"].equals(right["date"]):
        raise ValueError("Pairwise return calendar differs")
    av, bv = left["return"].to_numpy(), right["return"].to_numpy()
    ar, br = path_statistics(a["nav"], start=first, end=last), path_statistics(b["nav"], start=first, end=last)
    return {"account": a["identity"]["account"], "reference": b["identity"]["account"], "cost": a["identity"]["cost"],
        "start": first, "end": last, "sessions": len(av), "return_correlation": float(np.corrcoef(av, bv)[0, 1]),
        "cagr_difference": ar["cagr"] - br["cagr"], "sharpe_difference": ar["sharpe"] - br["sharpe"],
        "tracking_error_annual": float(np.std(av - bv, ddof=1) * np.sqrt(252)),
        "down_day_correlation": float(np.corrcoef(av[bv < 0], bv[bv < 0])[0, 1])}


def snapshot_overlap(a: dict, b: dict, year: int) -> dict | None:
    if year not in a["snapshots"] or year not in b["snapshots"]:
        return None
    sa, sb = a["snapshots"][year], b["snapshots"][year]
    if sa["date"] != sb["date"] or sa["frame"].is_empty() or sb["frame"].is_empty():
        return None
    x = sa["frame"].select("symbol", (pl.col("value") / sa["equity"]).alias("a_weight")).join(
        sb["frame"].select("symbol", (pl.col("value") / sb["equity"]).alias("b_weight")), on="symbol", how="full", coalesce=True).fill_null(0.)
    return {"account": a["identity"]["account"], "reference": b["identity"]["account"], "cost": a["identity"]["cost"],
        "year": year, "date": sa["date"], "shared_names": x.filter((pl.col("a_weight") > 0) & (pl.col("b_weight") > 0)).height,
        "union_names": x.height, "shared_equity_weight": x.select(pl.min_horizontal("a_weight", "b_weight").sum()).item(),
        "a_weight_in_b_names": x.filter(pl.col("b_weight") > 0)["a_weight"].sum(),
        "b_weight_in_a_names": x.filter(pl.col("a_weight") > 0)["b_weight"].sum(),
        "basis": "actual_year_end_holdings_not_daily_overlap"}


def holdings_evidence(accounts: list[dict], controls: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    rows, positions = [], []
    for a in accounts:
        for year, snap in a["snapshots"].items():
            frame = snap["frame"]
            if frame.is_empty():
                continue
            control = controls.filter(pl.col("trade_date") == snap["date"])
            base = control.filter(pl.col("eligible") & (pl.col("total_market_value") > 0))
            # Q10 has a different vintage: no substitution with current battery exposures.
            same_vintage = a["identity"]["snapshot_identity"] == "nightly_month_20260930"
            if same_vintage and base.height:
                q25, q75 = base["total_market_value"].quantile(.25), base["total_market_value"].quantile(.75)
                frame = frame.join(control.select("symbol", "total_market_value", "industry_l1"), on="symbol", how="left", validate="1:1")
                frame = frame.with_columns(pl.when(pl.col("total_market_value") <= 0).then(None).otherwise(pl.col("total_market_value")).alias("total_market_value"))
            else:
                q25 = q75 = None
                frame = frame.with_columns(pl.lit(None, dtype=pl.Float64).alias("total_market_value"), pl.lit(None, dtype=pl.String).alias("industry_l1"))
            frame = frame.with_columns((pl.col("value") / snap["equity"]).alias("weight"))
            investment = frame["weight"].sum()
            industry = frame.group_by("industry_l1").agg(pl.col("weight").sum())
            known_industry = industry.filter(pl.col("industry_l1").is_not_null())
            size_unknown = frame.filter(pl.col("total_market_value").is_null())["weight"].sum()
            small = frame.filter(pl.col("total_market_value") <= q25)["weight"].sum() if q25 else None
            large = frame.filter(pl.col("total_market_value") >= q75)["weight"].sum() if q75 else None
            rows.append({**a["identity"], "year": year, "date": snap["date"], "positions": frame.height,
                "invested_fraction": investment, "top5_actual_weight": frame.sort("weight", descending=True).head(5)["weight"].sum(),
                "top1_actual_weight": frame["weight"].max(), "effective_names": investment ** 2 / frame["weight"].pow(2).sum(),
                "smallest_quartile_equity_weight": small, "largest_quartile_equity_weight": large,
                "size_unknown_equity_weight": size_unknown,
                "industry_unknown_equity_weight": frame.filter(pl.col("industry_l1").is_null())["weight"].sum(),
                "largest_known_industry_equity_weight": known_industry["weight"].max() if known_industry.height else None,
                "exposure_identity": "exact_frozen_close_controls" if same_vintage else "unknown_other_vintage"})
            positions.extend({**a["identity"], "year": year, "date": snap["date"], **r} for r in frame.iter_rows(named=True))
    return pl.DataFrame(rows, infer_schema_length=None), pl.DataFrame(positions, infer_schema_length=None)


def run(config: Path) -> dict:
    cfg = tomllib.loads(config.read_text(encoding="utf-8"))
    ev, out = Evidence(), Path(cfg["output"])
    out.mkdir(parents=True, exist_ok=True)
    ev.track(config)
    for name in ["value_family_evidence.py", "value_family_holdings.py", "value_family_report.py", "value_family_decision.py"]:
        ev.track(Path(__file__).with_name(name))
    root, start, end = Path(cfg["battery"]), cfg["common_start"], cfg["common_end"]
    accounts, references = [], []
    for factor in cfg["factors"]:
        froot = root / "evaluation/costs" / factor
        ev.track(froot / "battery.toml")
        ev.track(froot / "share_exchanges.toml")
        frozen = ev.json(froot / "replay_config.json")
        assert frozen["snapshot"] == "nightly_month_20260930"
        for variant in cfg["variants"]:
            for cost in cfg["costs"]:
                identity = {"account": f"{factor}/{variant}/{cost:g}", "factor": factor, "variant": variant,
                    "cost": cost, "snapshot_identity": frozen["snapshot"]}
                accounts.append(read_account(ev, froot / variant / f"cost_{cost:g}", identity, cfg["snapshot_years"]))
    assert len(accounts) == 30
    assert max(a["nav"]["date"].min() for a in accounts) == start
    for ref, rroot in [("q10", Path(cfg["q10"])), *[("monthly_" + n, root / n) for n in cfg["monthly_models"]]]:
        frozen = ev.json(rroot / "replay_config.json")
        for cost in cfg["costs"]:
            ident = {"account": f"{ref}/budgeted/{cost:g}", "factor": ref, "variant": "budgeted", "cost": cost,
                     "snapshot_identity": frozen["snapshot"]}
            references.append(read_account(ev, rroot / "budgeted" / f"cost_{cost:g}", ident, cfg["snapshot_years"] if cost == 1 else []))
    # Prove the repaired benchmark's source matches this battery over the entire overlap.
    old, repair_source, repaired = [ev.parquet(Path(cfg[key])) for key in ["original_benchmark", "repair_source_benchmark", "repaired_benchmark"]]
    overlap = old.join(repair_source, on=["index_name", "trade_date"], suffix="_source")
    err = overlap.select((pl.col("daily_return") - pl.col("daily_return_source")).abs().max()).item()
    level_err = overlap.select((pl.col("index_level") - pl.col("index_level_source")).abs().max()).item()
    assert overlap.height == repair_source.height and err == level_err == 0.
    assert repaired["trade_date"].max() == end
    benchmark_identity = {"matched_rows": overlap.height, "max_original_return_difference": err,
        "max_original_level_difference": level_err, "repaired_snapshot": cfg["repaired_benchmark"],
        "pending_claim_valuation": "declared_stale_predecessor_book_value_not_observed_fair_value"}
    write_json(out / "benchmark_identity.json", benchmark_identity)
    benchmarks = {n: repaired.filter(pl.col("index_name") == n).sort("trade_date").select(
        pl.col("trade_date").alias("date"), (pl.col("index_level") / 1000).alias("unit_nav")) for n in repaired["index_name"].unique()}
    etf = ev.parquet(Path("data/clean/factor_benchmarks/nightly_month_20260930_etf/prices.parquet")).sort("trade_date")
    assert set(etf["symbol"]) == {"510300.SH"}
    benchmarks["510300_total_return"] = etf.select(pl.col("trade_date").alias("date"), (pl.col("adjusted_close") / etf["adjusted_close"][0]).alias("unit_nav")).slice(1)
    bench_metrics = {name: path_statistics(data, start=start, end=end) for name, data in benchmarks.items()}
    save(out / "benchmark_risk", pl.DataFrame([{"benchmark": n, **v} for n, v in bench_metrics.items()], infer_schema_length=None))
    metrics, annual, benchmark_rows, daily_rows, regression_rows, rejection_rows = [], [], [], [], [], []
    market = returns(benchmarks["all_market_equal_weight"], start, end).select("date", pl.col("return").alias("market"))
    market = market.join(returns(benchmarks["csi800_equal_weight"], start, end).select("date", pl.col("return").alias("csi800")), on="date", validate="1:1")
    for a in accounts:
        result = performance(a, start, end)
        metrics.append(result)
        daily = returns(a["nav"], start, end)
        for name, bench in benchmarks.items():
            grid = bench.filter(pl.col("date").is_between(start, end))["date"]
            assert grid.equals(daily["date"])
            benchmark_rows.append({**a["identity"], "benchmark": name, "start": start, "end": end,
                "cagr_excess": result["cagr"] - bench_metrics[name]["cagr"],
                "drawdown_difference": result["max_drawdown"] - bench_metrics[name]["max_drawdown"]})
        joined = daily.select("date", "return").join(market, on="date", validate="1:1")
        y, m, c = [joined[x].to_numpy() for x in ["return", "market", "csi800"]]
        for design_name, x in [("market_only", np.column_stack([np.ones(len(y)), m])),
                               ("market_plus_breadth_proxy", np.column_stack([np.ones(len(y)), m, m - c]))]:
            coef = np.linalg.lstsq(x, y, rcond=None)[0]
            residual = y - x @ coef
            regression_rows.append({**a["identity"], "design": design_name, "sessions": len(y),
                "market_beta": float(coef[1]), "breadth_relative_to_csi800_beta": float(coef[2]) if len(coef) > 2 else None,
                "r_squared": float(1 - np.var(residual) / np.var(y)),
                "arithmetic_intercept_times252": float(coef[0] * 252),
                "residual_annual_volatility": float(np.std(residual, ddof=1) * np.sqrt(252)),
                "interpretation": "descriptive_covariation_not_causal_alpha_or_pure_size"})
        daily_rows.append(daily.select("date", "return", "unit_nav", "equity", "position_count").with_columns(
            pl.lit(a["identity"]["account"]).alias("account")))
        for year in range(start.year, end.year + 1):
            block = daily.filter(pl.col("date").dt.year() == year)
            lo, hi = block["date"].min(), block["date"].max()
            row = path_statistics(a["nav"], start=lo, end=hi)
            annual.append({**a["identity"], "year": year, **row,
                "full_calendar_year": year not in {start.year, end.year},
                "log_return_contribution": float(np.log1p(row["total_return"]))})
        reject = a["rejections"].filter(pl.col("date").is_between(start, end))
        if reject.height:
            rejects = reject.with_columns((pl.col("rejected_quantity") * pl.col("reference_price")).alias("repeated_attempt_notional"))
            for row in rejects.group_by("reason", "side").agg(pl.len().alias("rejection_events"),
                pl.struct("date", "symbol").n_unique().alias("symbol_days"), pl.col("repeated_attempt_notional").sum()).iter_rows(named=True):
                rejection_rows.append({**a["identity"], **row})
    save(out / "common_window_metrics", pl.DataFrame(metrics, infer_schema_length=None))
    save(out / "calendar_year_metrics", pl.DataFrame(annual, infer_schema_length=None))
    save(out / "benchmark_comparisons", pl.DataFrame(benchmark_rows))
    save(out / "daily_returns", pl.concat(daily_rows))
    save(out / "market_covariation", pl.DataFrame(regression_rows, infer_schema_length=None))
    save(out / "rejection_reasons", pl.DataFrame(rejection_rows))
    return_pairs, holding_pairs = [], []
    for cost in cfg["costs"]:
        same = [a for a in accounts if a["identity"]["cost"] == cost]
        pairs = list(combinations(same, 2))
        pairs += [(a, b) for a in same for b in references if b["identity"]["cost"] == cost]
        for a, b in pairs:
            return_pairs.append(common_pair(a, b, start, end))
            if cost == 1:
                for year in cfg["snapshot_years"]:
                    row = snapshot_overlap(a, b, year)
                    if row:
                        holding_pairs.append(row)
    save(out / "return_overlap", pl.DataFrame(return_pairs))
    save(out / "actual_holdings_overlap", pl.DataFrame(holding_pairs))
    controls = []
    snapshot_dates = sorted({s["date"] for a in accounts for s in a["snapshots"].values()})
    for year in cfg["snapshot_years"]:
        path = ev.track(root / "evaluation/statistics/inputs" / str(year) / "universe.parquet")
        controls.append(pl.scan_parquet(path).filter(pl.col("trade_date").is_in(snapshot_dates)).select(
            "trade_date", "symbol", "eligible", "total_market_value", "industry_l1").collect())
    controls = pl.concat(controls)
    assert controls.select("trade_date", "symbol").unique().height == controls.height
    snapshot_summary, holdings = holdings_evidence(accounts + [a for a in references if a["identity"]["cost"] == 1], controls)
    save(out / "snapshot_exposures", snapshot_summary)
    save(out / "actual_snapshot_holdings", holdings)
    save(out / "actual_snapshot_industries", holdings.group_by("account", "factor", "variant", "cost", "year", "date", "industry_l1").agg(
        pl.col("weight").sum().alias("equity_weight"), pl.len().alias("names")))
    save(out / "snapshot_controls", controls)
    bridge_rows, bridge_totals = [], []
    for a in accounts:
        rows, totals = annual_security_bridge(a, cfg["security_contribution_years"])
        bridge_rows.extend(rows)
        bridge_totals.extend(totals)
    save(out / "security_mark_trade_bridge", pl.DataFrame(bridge_rows, infer_schema_length=None))
    save(out / "annual_bridge_reconciliation", pl.DataFrame(bridge_totals, infer_schema_length=None))
    save(out / "snapshot_nav_reconciliation", pl.DataFrame([x for a in accounts + references for x in a["checks"]]))
    # Attribute differences between saved cost paths descriptively; no no-cost counterfactual is created.
    cost_contrasts = []
    metric_table = pl.DataFrame(metrics, infer_schema_length=None)
    for factor in cfg["factors"]:
        for variant in cfg["variants"]:
            part = metric_table.filter((pl.col("factor") == factor) & (pl.col("variant") == variant))
            low, high = [part.filter(pl.col("cost") == c).row(0, named=True) for c in [.5, 2.]]
            cost_contrasts.append({"factor": factor, "variant": variant,
                "cagr_cost2_minus_cost05": high["cagr"] - low["cagr"],
                "annual_fee_plus_slippage_05": low["annual_fee_on_nav"] + low["annual_slippage_on_nav"],
                "annual_fee_plus_slippage_2": high["annual_fee_on_nav"] + high["annual_slippage_on_nav"],
                "trade_count_difference": high["trade_count"] - low["trade_count"],
                "interpretation": "saved_path_difference_includes_changed_quantities_and_fills_not_pure_fee_causality"})
    save(out / "cost_path_contrasts", pl.DataFrame(cost_contrasts))
    ev.verify()
    write_json(out / "source_manifest.json", list(ev.sources.values()))
    summary = {"factors": cfg["factors"], "factor_accounts": len(accounts), "reference_accounts": len(references),
        "common_start": start, "common_end": end, "window_reason": cfg["common_window_reason"],
        "benchmark_identity": benchmark_identity, "saved_snapshot_rows": holdings.height,
        "reconciled_snapshots": sum(len(a["checks"]) for a in accounts + references),
        "accounting_bridge_years": len(bridge_totals), "source_files_unchanged": len(ev.sources),
        "original_cash": 1000000, "original_minimum_commission": 5,
        "current_personal_account_suitability": "unknown_CNY100000_few_names_fee1_not_replayed",
        "daily_holdings": "unavailable_in_saved_factor_cost_paths_actual_year_end_only",
        "security_contribution_scope": "annual_ex_dividend_mark_trade_bridge_not_full_security_total_return",
        "unallocated_cash_scope": "dividends_receivables_corporate_action_and_other_cash_not_assigned_to_security",
        "q10_industry_size_exposure": "unknown_nonmatching_vintage_no_substitution",
        "auto_trade": False, "account_replays": 0}
    from quant.research.value_family_decision import conclude
    summary.update(conclude(out))
    write_json(out / "summary.json", summary)
    from quant.research.value_family_report import write_report
    write_report(out, summary)
    write_json(out / "diagnosis.ipynb", {"nbformat": 4, "nbformat_minor": 5,
        "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}},
        "cells": [{"cell_type": "markdown", "metadata": {}, "source": ["Saved-account diagnosis only. No replay. Run from repository root."]},
          {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
           "source": ["from pathlib import Path\n", "from quant.research.value_family_holdings import run\n", f"run(Path({str(config)!r}))"]}]})
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/research/value_family_holdings_20261004.toml"))
    args = parser.parse_args(argv)
    import json
    print(json.dumps(run(args.config), ensure_ascii=False, default=str, indent=2))


if __name__ == "__main__":
    main()
