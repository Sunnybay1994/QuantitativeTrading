"""Bounded full-library diagnosis using saved IC, states and cost receipts only."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tomllib

import polars as pl

from quant.research.market_mechanism_mapping import mechanism

DIMENSIONS = ["market_state", "liquidity_state", "sentiment_state", "volatility_state"]
KEYS = ["factor", "trade_date"]
NEUTRAL = "size_industry_neutral"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding="utf-8")


def save(path: Path, data: pl.DataFrame) -> None:
    sort_keys = [c for c in ["source", "basis", "dimension", "mechanism", "factor", "variant", "cost_multiplier", "state", "year", "trade_date", "size_reference"] if c in data.columns]
    if sort_keys:
        data = data.sort(sort_keys)
    data.write_parquet(path.with_suffix(".parquet"))
    if not any(isinstance(t, (pl.List, pl.Struct)) for t in data.schema.values()):
        data.write_csv(path.with_suffix(".csv"))


def aggregate(data: pl.DataFrame, keys: list[str], value: str) -> pl.DataFrame:
    valid = data.filter(pl.col(value).is_finite())
    annual = valid.group_by(*keys, "year").agg(
        pl.len().alias("months"), pl.col(value).mean().alias("annual_mean"))
    years = annual.group_by(keys).agg(
        pl.len().alias("years_observed"), (pl.col("annual_mean") > 0).mean().alias("positive_year_fraction"),
        (pl.col("months") >= 6).sum().alias("years_at_least_6_months"),
        pl.col("annual_mean").filter(pl.col("months") >= 6).gt(0).mean().alias("positive_qualified_year_fraction"),
        pl.col("annual_mean").min().alias("worst_year_mean_ic"),
        pl.col("annual_mean").max().alias("best_year_mean_ic"),
        (pl.col("months").max() / pl.col("months").sum()).alias("largest_year_month_share"))
    return valid.group_by(keys).agg(pl.len().alias("months"), pl.col(value).mean().alias("mean_ic"),
        (pl.col(value) > 0).mean().alias("positive_month_fraction")).join(years, on=keys)


def aligned_states(labels: pl.DataFrame, states: pl.DataFrame) -> pl.DataFrame:
    if labels["trade_date"].n_unique() != labels.height or states["trade_date"].n_unique() != states.height:
        raise ValueError("Ambiguous signal-date mapping")
    joined = labels.join(states.select("trade_date", "effective_date", "timing", "coverage_ok", *DIMENSIONS),
                         on="trade_date", how="left", validate="1:1")
    valid = ((pl.col("trade_date") < pl.col("execution_date_rebalance"))
             & (pl.col("effective_date") == pl.col("execution_date_rebalance"))).fill_null(False)
    return joined.with_columns(valid.alias("timing_aligned"),
        pl.when(pl.col("effective_date").is_null()).then(pl.lit("state_date_absent"))
        .when(~valid).then(pl.lit("effective_date_mismatch"))
        .otherwise(pl.lit("historical_reconstruction_not_arrival_proof")).alias("alignment_reason"),
        *[pl.when(valid).then(pl.col(c)).otherwise(pl.lit("unknown")).fill_null("unknown").alias(c)
          for c in DIMENSIONS])


def run(config_path: Path) -> dict:
    cfg = tomllib.loads(config_path.read_text(encoding="utf-8"))
    out, root = Path(cfg["output"]), Path(cfg["battery"])
    out.mkdir(parents=True, exist_ok=True)
    sources: dict[str, dict] = {}

    def track(path: Path) -> Path:
        key = path.as_posix()
        if key not in sources:
            sources[key] = {"path": key, "sha256": digest(path), "bytes": path.stat().st_size}
        return path

    track(config_path)
    track(Path(__file__))
    track(Path(__file__).with_name("market_mechanism_mapping.py"))
    track(Path(__file__).with_name("market_mechanism_report.py"))
    track(Path(__file__).with_name("factor_battery_statistics.py"))
    track(Path(__file__).with_name("factor_battery_evaluation.py"))
    mapping_file = track(out / "frozen_mapping.json")
    mapping_rows = json.loads(mapping_file.read_text(encoding="utf-8"))
    for row in mapping_rows:
        path = track(Path(row["definition_path"]))
        definition = tomllib.loads(path.read_text(encoding="utf-8"))
        assert digest(path) == row["definition_sha256"]
        assert mechanism(definition)[0] == row["mechanism"]
        assert definition["direction"] == row["direction"]
    mapping = pl.DataFrame(mapping_rows)
    assert mapping["factor"].n_unique() == len(list((root / "library").glob("*.toml"))) == 386
    save(out / "mapping", mapping)
    meta = mapping.select("factor", "mechanism", "original_family", "direction")
    stats = root / "evaluation/statistics"
    battery = tomllib.loads(track(stats / "battery.toml").read_text(encoding="utf-8"))
    assert battery["direction"] == "library_definition"
    assert battery["monthly_label"] == "next_open_to_next_monthly_rebalance_open"
    scorecard = pl.read_parquet(track(root / "evaluation/scorecard/factor_scorecard.parquet"))
    assert scorecard.select("factor", "variant").unique().height == 772
    ic = pl.concat([pl.read_parquet(track(stats / "factors" / name / "monthly_ic.parquet"))
                    .with_columns(pl.lit(name).alias("factor")) for name in mapping["factor"]])
    assert ic.select("factor", "variant", "trade_date").unique().height == ic.height
    # Saved IC is already directional and nulls already implement the frozen coverage screen.
    valid_ic = ic.filter(pl.col("rank_ic").is_finite())
    assert valid_ic.filter((pl.col("paired_count") < battery["minimum_symbols"])
                          | (pl.col("paired_coverage") < battery["minimum_paired_coverage"])).is_empty()
    check = valid_ic.group_by("factor", "variant").agg(pl.len().alias("n"), pl.col("rank_ic").mean().alias("reproduced"))
    check = scorecard.select("factor", "variant", "months", "mean_ic").join(check, on=["factor", "variant"], how="left")
    assert check.filter(pl.col("months") != pl.col("n").fill_null(0)).is_empty()
    max_ic_error = check.select((pl.col("mean_ic") - pl.col("reproduced")).abs().max()).item()
    assert max_ic_error < 1e-12
    save(out / "scorecard_reproduction", check)
    labels = []
    for path in sorted((stats / "inputs").glob("*/monthly_labels.parquet")):
        labels.append(pl.read_parquet(track(path), columns=["trade_date", "execution_date_rebalance", "exit_date_rebalance"]).unique())
    calendar = pl.concat(labels).unique().sort("trade_date")
    assert calendar["trade_date"].n_unique() == calendar.height
    # Every saved IC date must have the actual holding-period identity, including immature last labels.
    assert ic.select("trade_date").unique().join(calendar, on="trade_date", how="anti").is_empty()
    state_root = Path(cfg["states"])
    states = pl.read_parquet(track(state_root / "market_states.parquet"))
    track(state_root / "config.toml")
    aligned = aligned_states(calendar, states)
    save(out / "signal_state_alignment", aligned)
    ic = ic.join(meta, on="factor", validate="m:1").join(aligned, on="trade_date", how="left", validate="m:1")
    ic = ic.with_columns(pl.col("trade_date").dt.year().alias("year"))
    save(out / "factor_months", ic)
    factor_year = ic.filter(pl.col("rank_ic").is_finite()).group_by("factor", "mechanism", "variant", "year").agg(
        pl.len().alias("months"), pl.col("rank_ic").mean().alias("mean_ic"))
    save(out / "factor_years", factor_year)
    # Compare variants only for the same factor/month; neutralization also changes valid security cohort.
    paired = ic.filter(pl.col("variant") == "raw").select(*KEYS, "mechanism", "year", *DIMENSIONS,
        pl.col("rank_ic").alias("raw_ic"), pl.col("paired_count").alias("raw_stocks")).join(
        ic.filter(pl.col("variant") == NEUTRAL).select(*KEYS, pl.col("rank_ic").alias("neutral_ic"),
        pl.col("paired_count").alias("neutral_stocks")), on=KEYS, validate="1:1")
    paired = paired.filter(pl.col("raw_ic").is_finite() & pl.col("neutral_ic").is_finite()).with_columns(
        (pl.col("neutral_ic") - pl.col("raw_ic")).alias("neutral_minus_raw"))
    save(out / "paired_factor_months", paired)
    roster = meta.group_by("mechanism").len().rename({"len": "roster_factors"})
    family = paired.group_by("mechanism", "trade_date", "year", *DIMENSIONS).agg(
        pl.len().alias("available_factors"), pl.col("raw_ic").mean(), pl.col("neutral_ic").mean(),
        pl.col("neutral_minus_raw").mean()).join(roster, on="mechanism")
    family = family.with_columns((pl.col("available_factors") == pl.col("roster_factors")).alias("complete_roster"))
    save(out / "family_months", family)
    family_long = family.unpivot(on=["raw_ic", "neutral_ic"], index=["mechanism", "trade_date", "year", *DIMENSIONS,
        "available_factors", "roster_factors", "complete_roster"], variable_name="variant", value_name="ic")
    summaries, year_tables, cells, cell_years, contrasts = [], [], [], [], []
    for basis, sample in [("available_paired_members", family_long), ("complete_frozen_roster", family_long.filter(pl.col("complete_roster")))]:
        summaries.append(aggregate(sample, ["mechanism", "variant"], "ic").with_columns(pl.lit(basis).alias("basis")))
        year_tables.append(sample.group_by("mechanism", "variant", "year").agg(pl.len().alias("months"),
            pl.col("ic").mean().alias("mean_ic")).with_columns(pl.lit(basis).alias("basis")))
        for dim in DIMENSIONS:
            view = sample.rename({dim: "state"})
            keys = ["mechanism", "variant", "state"]
            cells.append(aggregate(view, keys, "ic").with_columns(pl.lit(basis).alias("basis"), pl.lit(dim).alias("dimension")))
            annual = view.group_by(*keys, "year").agg(pl.len().alias("months"), pl.col("ic").mean().alias("mean_ic"))
            cell_years.append(annual.with_columns(pl.lit(basis).alias("basis"), pl.lit(dim).alias("dimension")))
            # Within-year descriptive contrast avoids labeling an era difference as a state effect.
            known = view.filter(pl.col("state") != "unknown")
            for state in sorted(known["state"].unique().to_list()):
                a = known.filter(pl.col("state") == state).group_by("mechanism", "variant", "year").agg(
                    pl.len().alias("state_months"), pl.col("ic").mean().alias("state_mean"))
                b = known.filter(pl.col("state") != state).group_by("mechanism", "variant", "year").agg(
                    pl.len().alias("other_months"), pl.col("ic").mean().alias("other_mean"))
                contrasts.append(a.join(b, on=["mechanism", "variant", "year"]).with_columns(
                    (pl.col("state_mean") - pl.col("other_mean")).alias("within_year_difference"),
                    pl.lit(basis).alias("basis"), pl.lit(dim).alias("dimension"), pl.lit(state).alias("state")))
    save(out / "family_summary", pl.concat(summaries))
    save(out / "family_years", pl.concat(year_tables))
    save(out / "state_summary", pl.concat(cells))
    save(out / "state_years", pl.concat(cell_years))
    contrast = pl.concat(contrasts)
    save(out / "state_within_year_contrasts", contrast)
    save(out / "state_contrast_summary", contrast.group_by("basis", "dimension", "state", "mechanism", "variant").agg(
        pl.len().alias("paired_years"), pl.col("within_year_difference").mean().alias("equal_year_difference"),
        (pl.col("within_year_difference") > 0).mean().alias("positive_contrast_year_fraction"),
        pl.col("state_months").min().alias("minimum_state_months_in_year")))
    pairs = pl.read_parquet(track(root / "evaluation/redundancy/pairwise_correlations.parquet"))
    size_names = meta.filter(pl.col("mechanism") == "size_reference")["factor"].to_list()
    size_rows = []
    for size in size_names:
        size_rows.append(pairs.filter((pl.col("left") == size) | (pl.col("right") == size)).with_columns(
            pl.when(pl.col("left") == size).then(pl.col("right")).otherwise(pl.col("left")).alias("factor"),
            pl.lit(size).alias("size_reference")))
    size_corr = pl.concat(size_rows).join(meta.select("factor", "mechanism"), on="factor")
    save(out / "size_correlations", size_corr)
    # Save all cost outcomes and failures, with explicit original receipt identity.
    cost_cols = [c for c in scorecard.columns if c.startswith("cost_") or c in {
        "factor", "variant", "months", "mean_ic", "newey_west_t", "icir", "statistical_pass", "statistical_failures",
        "factor_admitted", "conclusion", "costs_complete", "return_benchmarks_complete", "measurement_current"}]
    cost_evidence = scorecard.select(cost_cols).join(meta.select("factor", "mechanism"), on="factor")
    save(out / "factor_cost_evidence", cost_evidence)
    cost_receipts = []
    for factor in meta["factor"]:
        path = root / "evaluation/costs" / factor / "summary.json"
        if path.exists():
            receipt = json.loads(track(path).read_text())
            for row in receipt.get("rows", []):
                cost_receipts.append({**row, "receipt_path": path.as_posix()})
    costs = pl.DataFrame(cost_receipts, infer_schema_length=None).join(meta.select("factor", "mechanism"), on="factor")
    cost_errors = []
    for mult, key in [(0.5, "0p5"), (1.0, "1"), (2.0, "2")]:
        measured = costs.filter(pl.col("cost_multiplier") == mult).join(
            scorecard.select("factor", "variant", pl.col(f"cost_{key}_cagr").alias("scorecard_cagr")),
            on=["factor", "variant"], validate="1:1")
        error = measured.select((pl.col("cagr") - pl.col("scorecard_cagr")).abs().max()).item()
        assert error is not None and error < 1e-12
        cost_errors.append(error)
    save(out / "saved_cost_receipts", costs)
    save(out / "family_cost_summary", costs.group_by("mechanism", "variant", "cost_multiplier").agg(
        pl.len().alias("factors_with_saved_costs"), pl.col("cagr").median().alias("median_cagr"),
        pl.col("sharpe").median().alias("median_sharpe"), pl.col("annualized_one_way_turnover").median().alias("median_turnover"),
        pl.col("max_drawdown").median().alias("median_drawdown")).join(roster, on="mechanism"))
    # Historical partial IC is retained as a separate model-specific cohort, never substituted for current battery IC.
    old_partial = []
    incremental_identity = []
    for source in cfg["incremental"]:
        base = Path(source)
        old_cfg = tomllib.loads(track(base / "config.toml").read_text(encoding="utf-8"))
        old_model = Path(old_cfg["source"]) / "predictions/model.toml"
        if old_model.exists():
            track(old_model)
        old = pl.read_parquet(track(base / "monthly_incremental_ic.parquet"))
        old = old.join(meta.select("factor", "mechanism"), on="factor", how="left").with_columns(pl.lit(source).alias("source"))
        old_partial.append(old)
        comparison = old.join(ic.filter(pl.col("variant") == NEUTRAL).select(*KEYS, "rank_ic"), on=KEYS)
        comparable = comparison.filter(pl.col("rank_ic").is_finite() & pl.col("raw_rank_ic").is_finite())
        incremental_identity.append({"source": source, "model": old_cfg["source"], "factors": old["factor"].n_unique(),
            "matched_factor_months": comparable.height,
            "different_raw_ic_months": comparable.filter((pl.col("rank_ic") - pl.col("raw_rank_ic")).abs() > 1e-10).height,
            "current_battery_incremental_identity": "not_equivalent_old_model_controls_imputation_cohort_and_snapshot",
            "usable_as": "historical_model_specific_clue_only"})
    partial = pl.concat(old_partial, how="diagonal_relaxed")
    partial = partial.with_columns(pl.col("trade_date").dt.year().alias("year"))
    save(out / "historical_partial_months", partial)
    partial_summary = partial.group_by("source", "factor", "mechanism").agg(
        pl.len().alias("total_months"), pl.col("partial_rank_ic").is_finite().sum().alias("identified_months"),
        pl.col("partial_rank_ic").mean().alias("mean_partial_ic"), pl.col("raw_rank_ic").mean().alias("mean_raw_ic"),
        pl.col("raw_rank_ic").filter(pl.col("partial_rank_ic").is_finite()).mean().alias("same_identified_months_raw_ic"))
    save(out / "historical_partial_summary", partial_summary)
    save(out / "historical_partial_years", partial.group_by("source", "factor", "mechanism", "year").agg(
        pl.col("partial_rank_ic").is_finite().sum().alias("identified_months"),
        pl.col("partial_rank_ic").mean().alias("mean_partial_ic")))
    dump(out / "incremental_identity.json", incremental_identity)
    coverage = aligned.unpivot(on=DIMENSIONS, index=["trade_date", "alignment_reason"], variable_name="dimension", value_name="state")
    save(out / "state_coverage", coverage.group_by("dimension", "state").len().sort("dimension", "state"))
    summary = {
        "scope": cfg["scope"], "factors": mapping.height, "variants": scorecard.height,
        "financial_factors": meta.filter(pl.col("original_family") == "pit_financial").height,
        "mechanisms": roster.sort("mechanism").to_dicts(), "signal_dates": calendar.height,
        "state_dates_aligned": aligned.filter(pl.col("timing_aligned")).height,
        "state_dates_absent": aligned.filter(pl.col("alignment_reason") == "state_date_absent").height,
        "effective_date_mismatches": aligned.filter(pl.col("alignment_reason") == "effective_date_mismatch").height,
        "state_source_start": str(states["trade_date"].min()), "state_source_end": str(states["trade_date"].max()),
        "known_ic_through": str(valid_ic["trade_date"].max()), "scorecard_max_ic_error": max_ic_error,
        "factor_month_rows": ic.height, "finite_ic_rows": valid_ic.height,
        "paired_factor_months": paired.height,
        "statistical_pass_variants": scorecard["statistical_pass"].sum(),
        "saved_admitted_variants": scorecard["factor_admitted"].sum(),
        "cost_complete_variants": scorecard["costs_complete"].sum(),
        "complete_return_benchmark_variants": scorecard["return_benchmarks_complete"].sum(),
        "saved_cost_receipt_rows": costs.height,
        "cost_receipt_max_cagr_error": max(cost_errors),
        "financial_complete_roster": pl.concat(summaries).filter(
            (pl.col("basis") == "complete_frozen_roster") & (pl.col("variant") == "neutral_ic")
            & pl.col("mechanism").is_in(["value_dividend", "cash_quality", "profitability", "investment_accrual", "growth_surprise", "balance_sheet_safety", "composite_quality"])).sort("mechanism").to_dicts(),
        "original_cost_identity": {"initial_cash": battery["portfolio"]["initial_cash"],
            "commission_min": battery["costs"]["a_share"]["commission_min"],
            "cost_multipliers": battery["portfolio"]["cost_multipliers"], "portfolio": battery["portfolio"]["top_group_weights"]},
        "incremental_identity": incremental_identity,
        "limitations": ["Historical state reconstruction is not an original arrival-time receipt",
            "Raw-neutral gap includes industry, size and valid-security-cohort changes; it is not pure size attribution",
            "Family mean IC is descriptive, not IC or net return of a tradable family portfolio",
            "Sparse state slices receive no t-test; years and within-year contrasts are descriptive",
            "Saved state-independent cost paths cannot prove net regime switching benefit",
            "Stock return-benchmark gaps and original cost account identity are preserved",
            "No personal account cost evidence or same-snapshot incremental IC was manufactured"],
        "decision": "stop_state_timing_extension_no_new_account_hypothesis_from_this_diagnosis",
        "next_direction": "Prioritize the independent valuation/cash-flow-price mechanism outside market timing: audit the five already-admitted value/dividend factors together using saved holdings, concentration, fills and historical partial IC. No new account or single-factor hypothesis; abandon extension if the saved evidence shows only existing-model overlap or inadequate net risk performance. Do not rescue weak cash-quality or accrual mechanisms with state/window tuning.",
        "auto_trade": False,
    }
    # End-of-run verification detects concurrent changes in every consumed source, without touching writers.
    assert all(digest(Path(row["path"])) == row["sha256"] for row in sources.values())
    summary["unchanged_source_files"] = len(sources)
    dump(out / "source_manifest.json", list(sources.values()))
    dump(out / "summary.json", summary)
    receipt_rows = [{k: row[k] for k in ["mechanism", "months", "mean_ic", "years_at_least_6_months", "positive_qualified_year_fraction"]}
                    for row in summary["financial_complete_roster"]]
    dump(out / "sources.json", {"schemaVersion": 1, "items": [{"id": "full-library-mechanisms", "title": "全库机制诊断：完整财务家族",
        "queries": [{"id": "financial-roster", "source": {"label": "Frozen October battery monthly IC plus fixed expression/source mapping",
            "caveats": summary["limitations"]}, "columns": list(receipt_rows[0]), "rows": receipt_rows, "rowCount": len(receipt_rows)}]}]})
    from quant.research.market_mechanism_report import write_report
    write_report(out, summary)
    notebook = {"nbformat": 4, "nbformat_minor": 5,
        "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}},
        "cells": [{"cell_type": "markdown", "metadata": {}, "source": ["Run from repository root. Uses saved evidence only; no accounts or battery rerun."]},
        {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
         "source": ["from pathlib import Path\n", "from quant.research.market_mechanism import run\n", f"run(Path({str(config_path)!r}))"]}]}
    dump(out / "diagnosis.ipynb", notebook)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/research/market_mechanism_20261004.toml"))
    args = parser.parse_args(argv)
    print(json.dumps(run(args.config), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
