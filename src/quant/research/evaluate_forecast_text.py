"""One-command P7 statistics plus same-support incremental diagnostics."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import tomllib

import polars as pl

from quant.data.forecast_text_evaluation import read_forecast_controls, read_text_evaluation_year
from quant.data.forecast_text_scores import publish_panels
from quant.factors.forecast_text_score import DIMENSIONS
from quant.research.forecast_text_incremental import diagnose_sections, summarize_incremental
from quant.research.score_forecast_text import load_design


def write_incremental(parts: list[pl.DataFrame], supports: list[pl.DataFrame], *, output: Path,
                      sessions: tuple[dt.date, ...], settings: dict, design: dict,
                      synthetic: bool) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    points = pl.concat(parts, how="vertical_relaxed")
    support = pl.concat(supports, how="vertical_relaxed")
    summary = {"synthetic_fixture": synthetic, "purpose": "incremental_diagnostic_only",
               "minimum_months": settings["admission"]["minimum_months"],
               "minimum_symbols": settings["minimum_symbols"],
               "regression_inputs": ["intercept", "forecast_p_change_midpoint", "pit_sue8",
                                     "log_total_market_value", "industry_dummies"],
               "returns_used_in_regression": False,
               "summary": summarize_incremental(points, sessions=sessions, settings=settings, design=design)}
    points.write_parquet(output / "incremental_ic.parquet")
    support.write_parquet(output / "common_support.parquet")
    coverage = points.filter(pl.col("comparator") == "text").with_columns(
        pl.col("trade_date").dt.year().alias("year"))
    coverage.write_csv(output / "coverage_by_date.csv")
    coverage.group_by("factor", "frequency", "year").agg(
        pl.len().alias("dates"), pl.col("common_count").median().alias("median_common_symbols"),
        pl.col("text_complete_case_fraction").mean().alias("mean_complete_case_fraction"),
        (pl.col("common_count") >= settings["minimum_symbols"]).sum().alias("dates_at_minimum_symbols"),
    ).sort("factor", "frequency", "year").write_csv(output / "coverage_by_year.csv")
    (output / "summary.json").write_text(json.dumps(summary, default=str, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def run_incremental(*, run: Path, statistics: Path, data_root: Path, output: Path,
                    design: dict) -> dict:
    from quant.data.factor_panels import available_sessions

    report = json.loads((run / "run.json").read_text(encoding="utf-8"))
    if report["dry_run"]:
        raise ValueError("Real incremental evaluation requires live scores; use --fixture for synthetic tests")
    settings = tomllib.loads((statistics / "battery.toml").read_text(encoding="utf-8"))
    numeric = read_forecast_controls(Path(report["source"]))
    points, supports = [], []
    for year in range(design["start"].year, design["end"].year + 1):
        folder = statistics / "inputs" / str(year)
        universe = pl.read_parquet(folder / "universe.parquet")
        panel, daily_labels = read_text_evaluation_year(data_root=data_root, year=year,
            known_through=design["end"], universe=universe, numeric_events=numeric,
            factors=[f"text_{name}" for name in DIMENSIONS],
            max_age_days=design["maximum_age_calendar_days"])
        monthly_labels = pl.read_parquet(folder / "monthly_labels.parquet")
        keys = ["symbol", "trade_date"]
        daily = panel.join(daily_labels.select(*keys, "label_20"), on=keys, how="left", validate="1:1")
        monthly_dates = monthly_labels["trade_date"].unique()
        monthly = panel.filter(pl.col("trade_date").is_in(monthly_dates.implode())).join(
            monthly_labels.select(*keys, "label_rebalance"), on=keys, how="left", validate="1:1")
        for section, label, frequency in ((daily, "label_20", "daily_20"),
                                           (monthly, "label_rebalance", "monthly")):
            part, common = diagnose_sections(section, label=label, frequency=frequency, settings=settings)
            points.append(part)
            supports.append(common)
    return write_incremental(points, supports, output=output, design=design, settings=settings,
        sessions=available_sessions(data_root, design["end"]), synthetic=False)


def run_pipeline(*, run: Path, output: Path, data_root: Path, design_path: Path,
                 workers: int = 1, execution_snapshot: str | None = None) -> dict:
    from quant.research.factor_battery_batch import run_statistics
    from quant.research.factor_battery_screen import run_screen

    design = load_design(design_path)
    output.mkdir(parents=True, exist_ok=False)
    publication = publish_panels(run, data_root=data_root, design=design)
    library = Path("configs/factors/p7_text_library")
    statistics = output / "statistics"
    run_statistics(data_root=data_root, config=run / "battery.toml", library=library,
                   as_of=design["end"], output=statistics, workers=workers)
    screen = run_screen(statistics=statistics, output=output / "screen", library=library)
    incremental = run_incremental(run=run, statistics=statistics, data_root=data_root,
                                  output=output / "incremental", design=design)
    costs = None
    if execution_snapshot:
        from quant.research.factor_battery_cost_batch import run_cost_batch

        costs = run_cost_batch(statistics=statistics, screen=output / "screen", output=output / "costs",
            data_root=data_root, execution_snapshot=execution_snapshot, existing_runs=[], workers=workers)
    summary = {"synthetic_fixture": False, "publication": publication, "screen": screen,
        "incremental_series": len(incremental["summary"]), "costs": costs,
        "conclusion": "RESEARCH_ONLY",
        "next_step": "Use existing full-library redundancy/benchmarks/scorecard; residual IC is diagnostic only"}
    (output / "summary.json").write_text(json.dumps(summary, default=str, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def run_fixture(*, source: Path, output: Path, design_path: Path) -> dict:
    """Explicit synthetic CLI rehearsal; never publishes factors or calls a provider."""
    from quant.research.factor_battery_evaluation import evaluate_factor_year, summarize_factor_statistics

    design = load_design(design_path)
    settings = tomllib.loads(Path(design["battery"]).read_text(encoding="utf-8"))
    panel = pl.read_parquet(source)
    if ("synthetic_fixture" not in panel.columns or not panel.height
            or panel["synthetic_fixture"].null_count() or not panel["synthetic_fixture"].all()):
        raise ValueError("Fixture rows must explicitly declare synthetic_fixture=true")
    panel = panel.filter(pl.col("trade_date").is_between(design["start"], design["end"]))
    if panel.is_empty():
        raise ValueError("Fixture must be within the frozen design window")
    keys = ["symbol", "trade_date"]
    monthly = panel.filter(pl.col("is_month_end"))
    sessions = tuple(panel["trade_date"].unique().sort().to_list())
    output.mkdir(parents=True, exist_ok=False)
    points, supports = [], []
    for frame, label, frequency in ((panel, "label_20", "daily_20"), (monthly, "label_rebalance", "monthly")):
        part, common = diagnose_sections(frame, label=label, frequency=frequency, settings=settings)
        points.append(part)
        supports.append(common)
    # Exercise the same existing raw/neutralized statistics using explicitly synthetic labels.
    battery: list[dict] = []
    for factor, direction in zip(DIMENSIONS, (1, -1, -1), strict=True):
        statistics_part = evaluate_factor_year(universe=panel,
            values=panel.select(*keys, pl.col(f"text_{factor}").alias("value")),
            daily_labels=panel.select(*keys, *[f"label_{h}" for h in settings["decay_sessions"]]),
            monthly_labels=monthly.select(*keys, "label_rebalance"), direction=direction, settings=settings)
        rows, _ = summarize_factor_statistics([statistics_part], sessions=sessions, settings=settings)
        battery.extend({"factor": f"text_{factor}", "synthetic_fixture": True, **row} for row in rows)
    (output / "synthetic_battery.json").write_text(json.dumps(battery, default=str, indent=2), encoding="utf-8")
    result = write_incremental(points, supports, output=output / "incremental", sessions=sessions,
                               settings=settings, design=design, synthetic=True)
    return {"synthetic_fixture": True, "battery_variants": len(battery),
            "incremental_summaries": len(result["summary"])}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--run", type=Path)
    selection.add_argument("--fixture", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--design", type=Path, default=Path("configs/factors/p7_text_evaluation_v2.toml"))
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--execution-snapshot")
    args = parser.parse_args()
    if args.fixture:
        result = run_fixture(source=args.fixture, output=args.output, design_path=args.design)
    else:
        result = run_pipeline(run=args.run, output=args.output, data_root=args.data_root,
            design_path=args.design, workers=args.workers, execution_snapshot=args.execution_snapshot)
    print(json.dumps(result, default=str, ensure_ascii=False))


if __name__ == "__main__":
    main()
