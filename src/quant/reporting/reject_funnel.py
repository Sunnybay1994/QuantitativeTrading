"""B3: map REJECTED rows to the first failed admission gate (advisory)."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import polars as pl

from quant.reporting.experiment_registry import DEFAULT_REGISTRY

STAGES = (
    "statistics",
    "fdr",
    "cost",
    "correlation",
    "incremental",
    "strategy_excess",
    "strategy_sharpe",
    "turnover",
    "drawdown",
    "stress",
    "annual_hit",
    "unknown",
)


def classify_factor_row(row: dict) -> tuple[str, str]:
    """Best-effort first-fail stage from a factor scorecard row."""
    if row.get("statistical_pass") is False:
        failures = row.get("statistical_failures")
        return "statistics", f"statistical_failures={failures}"
    if row.get("bh_discovery") is False or row.get("bh_pass") is False:
        return "fdr", f"bh_adjusted_p={row.get('bh_adjusted_p')}"
    if row.get("redundancy_pass") is False or row.get("redundant_with_higher") is True:
        return "correlation", (
            f"higher_max_abs_rank_corr={row.get('higher_max_absolute_rank_correlation')}"
        )
    if row.get("cost_excess_pass") is False:
        return "cost", "cost_excess_pass=false"
    if row.get("incremental_pass") is False:
        return "incremental", "incremental_pass=false"
    if row.get("factor_admitted") is False:
        return "unknown", "factor_admitted=false_without_earlier_gate"
    return "unknown", "no_stage_fields"


def classify_strategy_checks(checks: dict) -> tuple[str, str]:
    order = (
        ("net_excess", "strategy_excess"),
        ("double_cost_excess", "strategy_excess"),
        ("sharpe", "strategy_sharpe"),
        ("turnover", "turnover"),
        ("max_drawdown", "drawdown"),
        ("drawdown", "drawdown"),
        ("stress", "stress"),
        ("annual", "annual_hit"),
        ("annual_outperformance", "annual_hit"),
    )
    for key, stage in order:
        for name, value in checks.items():
            if value is False and (key in name):
                return stage, f"{name}=false"
    failed = [k for k, v in checks.items() if v is False]
    if failed:
        return "unknown", ",".join(failed)
    return "unknown", "rejected_without_false_check"


def _classify_from_run(row: dict) -> tuple[str, str]:
    run = Path(row.get("run_path") or "")
    report = Path(row.get("report_path") or "")
    assessment = report.parent / "assessment.json"
    if assessment.exists():
        data = json.loads(assessment.read_text(encoding="utf-8"))
        for block in (data.get("assessments") or {}).values():
            if isinstance(block, dict) and isinstance(block.get("checks"), dict):
                return classify_strategy_checks(block["checks"])
    summary_path = run / "summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        scorecard = summary.get("scorecard_path")
        if scorecard and Path(scorecard).exists():
            frame = pl.read_parquet(scorecard)
            variant = row.get("variant") or ""
            # variant often "factor/raw"
            if "/" in variant:
                factor, var = variant.split("/", 1)
                match = frame.filter((pl.col("factor") == factor) & (pl.col("variant") == var))
            else:
                match = frame.filter(pl.col("factor") == row.get("experiment_id"))
            if match.height:
                return classify_factor_row(match.to_dicts()[0])
        # N3 digest style
        for key in ("reject_stage", "first_fail_gate"):
            if summary.get(key):
                return str(summary[key]), str(summary.get("reject_detail") or "")[:200]
    return "unknown", ""


def backfill_registry(registry: Path = DEFAULT_REGISTRY, *, since: dt.date | None = None) -> dict:
    rows = pl.read_parquet(registry).to_dicts()
    updated = 0
    staged = 0
    scope = [r for r in rows if r.get("conclusion") == "REJECTED"]
    if since:
        scope = [r for r in scope if not r.get("result_time") or r["result_time"][:10] >= since.isoformat()]
    for row in scope:
        if row.get("reject_stage") in STAGES and row["reject_stage"] != "unknown":
            staged += 1
            continue
        stage, detail = _classify_from_run(row)
        row["reject_stage"] = stage
        row["reject_detail"] = detail
        updated += 1
        if stage != "unknown":
            staged += 1
    # Write all rows (including non-scope) with updated reject fields on scoped rows.
    frame = pl.DataFrame(rows, infer_schema_length=None)
    temporary = registry.with_suffix(".parquet.tmp")
    frame.write_parquet(temporary)
    temporary.replace(registry)
    rejected = len(scope)
    return {
        "rejected_rows_in_scope": rejected,
        "updated": updated,
        "staged_known": staged,
        "known_fraction": (staged / rejected) if rejected else None,
    }

def funnel_table(registry: Path = DEFAULT_REGISTRY, *, since: dt.date | None = None) -> pl.DataFrame:
    frame = pl.read_parquet(registry)
    if "reject_stage" not in frame.columns:
        frame = frame.with_columns(pl.lit(None).cast(pl.Utf8).alias("reject_stage"))
    rejected = frame.filter(pl.col("conclusion") == "REJECTED")
    if since is not None and "result_time" in rejected.columns:
        rejected = rejected.filter(pl.col("result_time") >= since.isoformat())
    return (
        rejected.group_by(pl.col("reject_stage").fill_null("unknown"))
        .len()
        .rename({"reject_stage": "stage", "len": "n"})
        .sort("n", descending=True)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--since", type=dt.date.fromisoformat, default=None)
    parser.add_argument("--backfill", action="store_true")
    args = parser.parse_args()
    result = {}
    if args.backfill:
        result["backfill"] = backfill_registry(args.registry, since=args.since)
    table = funnel_table(args.registry, since=args.since)
    result["funnel"] = table.to_dicts()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if table.height:
        print(table)


if __name__ == "__main__":
    main()
