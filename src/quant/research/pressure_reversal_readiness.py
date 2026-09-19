"""Read-only, bounded input checks for the proposed daily pressure-reversal battery.

Does not read future return labels, enqueue factors, or change shared data.
Sampled coverage and AST equality are deliberately not full-history admission checks.
"""
from __future__ import annotations

import argparse
import ast
import bisect
import calendar
import datetime as dt
import hashlib
import json
import tomllib
from pathlib import Path

import polars as pl

from quant.data.factor_panels import available_sessions, read_factor_inputs
from quant.data.industry_history import attach_industry
from quant.factors.expressions import evaluate_expressions, required_history
from quant.factors.library import load_library


def expression_key(expression: str) -> str:
    return ast.dump(ast.parse(expression, mode="eval"), include_attributes=False)


def profile(panel: pl.DataFrame, bars: pl.DataFrame, expressions: dict[str, str],
            start: dt.date, end: dt.date) -> dict:
    keys = ["symbol", "trade_date"]
    current = bars.filter(pl.col("trade_date").is_between(start, end)).select(keys)
    selected = panel.join(current, on=keys, how="semi")
    values = evaluate_expressions(panel, expressions).join(current, on=keys, how="semi")
    fields = ["adj_close", "amount", "industry_l1"]
    duplicate_rows = selected.select(pl.struct(keys).is_duplicated().sum()).item()
    return {
        "start": str(start), "end": str(end), "observed_stock_days": selected.height,
        "symbols": selected["symbol"].n_unique(),
        "sessions": selected["trade_date"].n_unique(), "duplicate_key_rows": duplicate_rows,
        "null_rows": {c: selected[c].null_count() for c in fields},
        "nonpositive_amount_rows": selected.filter(pl.col("amount") <= 0).height,
        "nonfinite_numeric_rows": {
            c: selected.filter(pl.col(c).is_not_null() & ~pl.col(c).is_finite()).height
            for c in fields[:2]
        },
        "signal_finite_rows": {c: values[c].is_finite().sum() for c in expressions},
        "scope": "Observed bar keys only; padded warmup sessions excluded from counts",
    }


def run(config: Path, output: Path) -> dict:
    settings = tomllib.loads(config.read_text(encoding="utf-8"))
    if settings["stage"] != "input_readiness_only" or settings["enqueue"] or settings["auto_trade"]:
        raise ValueError("This command only supports read-only input readiness")
    output.mkdir(parents=True, exist_ok=False)
    (output / "config.toml").write_bytes(config.read_bytes())
    refresh = Path(settings["refresh_config"])
    # Freeze the actual data selection even if the production refresh later changes it.
    frozen_refresh = output / "refresh_config.toml"
    frozen_refresh.write_bytes(refresh.read_bytes())
    data_root = Path(settings["data_root"])
    publications = sorted((data_root / "clean/tushare_industry").glob("*/summary.json"), reverse=True)
    publication = next(p for p in publications
                       if json.loads(p.read_text(encoding="utf-8"))["with_current"])
    industry_path = publication.parent / "intervals.parquet"
    intervals = pl.read_parquet(industry_path)
    expressions = {r["id"]: r["expr"] for r in settings["candidates"] + settings["controls"]}
    history = max(required_history(x) for x in expressions.values())
    definitions = load_library(Path(settings["library"]))
    duplicates = {r["id"]: [d.id for d in definitions
                           if expression_key(d.expr) == expression_key(r["expr"])]
                  for r in settings["candidates"]}
    end = dt.date.fromisoformat(settings["history_end"])
    sessions = available_sessions(data_root, end)
    samples = []
    for month in settings["sample_months"]:
        year, number = map(int, month.split("-"))
        low = dt.date(year, number, 1)
        high = min(end, dt.date(year, number, calendar.monthrange(year, number)[1]))
        if low > high or not any(low <= d <= high for d in sessions):
            raise ValueError(f"No configured sample sessions: {month}")
        read_start = sessions[max(0, bisect.bisect_left(sessions, low) - history)]
        panel, bars = read_factor_inputs(data_root, frozen_refresh, read_start, high, sessions)
        panel = attach_industry(panel, intervals)
        samples.append(profile(panel, bars, expressions, low, high))
        print(json.dumps({"sample_month": month, "observed_stock_days": samples[-1]["observed_stock_days"]}), flush=True)
    result = {
        "generated_at": dt.datetime.now().isoformat(), "config": str(config),
        "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
        "refresh_config_sha256": hashlib.sha256(frozen_refresh.read_bytes()).hexdigest(),
        "industry_publication": str(publication),
        "industry_sha256": hashlib.sha256(industry_path.read_bytes()).hexdigest(),
        "library_count": len(definitions), "candidate_count": len(settings["candidates"]),
        "exact_ast_duplicates": duplicates, "samples": samples,
        "queued": False, "return_labels_read": False, "auto_trade": False,
        "conclusion": "INPUT_DIAGNOSTIC_ONLY",
        "limitations": [
            "Five sampled months do not establish complete historical coverage or 96-month eligibility",
            "AST differences do not establish distinct signals; full-history signal equivalence remains open",
            "Dated industry intervals are used; historical source revision timing is not independently proven",
            "Volume-price inputs cannot establish the absence of information or news",
            "No returns, decay, exit impact, SUE complementarity or strategy performance measured",
        ],
        "next_step": "Check full-history coverage and existing signal equivalence before queueing this fixed battery",
    }
    (output / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Pressure reversal input readiness", "", "Input diagnostic only; no candidates queued.", "",
             "| Month | Stock-days | Missing industry | Finite candidate 1 | Finite candidate 2 |",
             "|---|---:|---:|---:|---:|"]
    ids = [r["id"] for r in settings["candidates"]]
    for row in samples:
        lines.append(f"| {row['start'][:7]} | {row['observed_stock_days']} | "
                     f"{row['null_rows']['industry_l1']} | {row['signal_finite_rows'][ids[0]]} | "
                     f"{row['signal_finite_rows'][ids[1]]} |")
    lines += ["", *[f"- {x}" for x in result["limitations"]], "", f"Next: {result['next_step']}"]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/research/pressure_reversal_v1.toml"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.config, args.output)
    print(json.dumps({"output": str(args.output), "conclusion": result["conclusion"]}))


if __name__ == "__main__":
    main()
