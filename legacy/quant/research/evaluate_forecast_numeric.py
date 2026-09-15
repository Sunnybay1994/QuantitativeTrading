"""Compute the small P7 numeric batch using the existing factor battery."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import tomllib
from pathlib import Path

import polars as pl

from quant.factors.compute import run as compute_factors
from quant.factors.library import load_library
from quant.research.factor_battery_batch import run_statistics
from quant.research.factor_battery_cost_batch import run_cost_batch
from quant.research.factor_battery_scorecard import run_scorecard
from quant.research.factor_battery_screen import run_screen


def reuse_inputs(*, source: Path, output: Path, battery: Path, as_of: dt.date) -> None:
    """Only copy universe/label inputs from the identical dated battery."""
    expected = tomllib.loads(battery.read_text(encoding="utf-8"))
    actual = tomllib.loads((source / "battery.toml").read_text(encoding="utf-8"))
    run = actual.pop("run")
    if actual != expected or run["as_of"] != as_of:
        raise ValueError("Cached universe and labels require identical battery settings and as_of")
    for year in range(expected["start"].year, as_of.year + 1):
        folder = output / "inputs" / str(year)
        folder.mkdir(parents=True, exist_ok=True)
        for name in ("universe.parquet", "monthly_labels.parquet"):
            target = folder / name
            if not target.exists():
                shutil.copyfile(source / "inputs" / str(year) / name, target)


def monthly_coverage(scores: pl.DataFrame, ic: pl.DataFrame, *, symbols: list[str],
                     factor: str, variants: list[str]) -> pl.DataFrame:
    """Separate value coverage in the requested scope from future-label pairing."""
    requested = pl.col("symbol").is_in(symbols)
    frames = []
    for variant in variants:
        valid = pl.col(variant).is_finite().fill_null(False)
        coverage = scores.group_by("trade_date").agg(
            pl.len().alias("eligible_stocks"), requested.sum().alias("eligible_requested_stocks"),
            valid.sum().alias("valid_stocks"), (valid & requested).sum().alias("valid_requested_stocks"),
        ).with_columns(
            pl.when(pl.col("eligible_stocks") > 0)
            .then(pl.col("valid_stocks") / pl.col("eligible_stocks")).alias("universe_coverage"),
            pl.when(pl.col("eligible_requested_stocks") > 0)
            .then(pl.col("valid_requested_stocks") / pl.col("eligible_requested_stocks"))
            .alias("requested_coverage"),
        )
        frames.append(coverage.join(ic.filter(pl.col("variant") == variant), on="trade_date",
                                    how="full", coalesce=True, validate="1:1")
                      .with_columns(pl.lit(factor).alias("factor")))
    return pl.concat(frames).sort("factor", "variant", "trade_date")


def run_pipeline(*, config: Path, output: Path, data_root: Path = Path("data"),
                 workers: int = 2, costs: bool = False, resume: bool = False) -> dict:
    design_text = config.read_text(encoding="utf-8")
    design = tomllib.loads(design_text)
    battery, library = Path(design["battery"]), Path(design["library"])
    settings = tomllib.loads(battery.read_text(encoding="utf-8"))
    refresh = Path(design["refresh_config"])
    benchmark = Path(design["return_benchmark_config"])
    scope_text = Path(design["scope"]).read_text(encoding="utf-8")
    definitions = load_library(library)
    if (workers < 1 or design["start"] != settings["start"]
            or design["maximum_age_calendar_days"] != 120
            or {d.id: d.direction for d in definitions} != {
                "forecast_p_change_midpoint": 1, "forecast_p_change_width": -1}):
        raise ValueError("Requires the registered two-factor numeric batch and 120-day lifetime")
    configuration = {"design": design_text, "battery": battery.read_text(encoding="utf-8"),
        "refresh": refresh.read_text(encoding="utf-8"),
        "benchmarks": benchmark.read_text(encoding="utf-8"),
        "scope": scope_text,
        "library": {p.name: p.read_text(encoding="utf-8") for p in sorted(library.glob("*.toml"))},
        "data_root": str(data_root.resolve())}
    saved = output / "configuration.json"
    if resume:
        if not saved.is_file() or json.loads(saved.read_text(encoding="utf-8")) != configuration:
            raise ValueError("Resume requires the same numeric configuration and inputs")
    else:
        output.mkdir(parents=True, exist_ok=False)
        saved.write_text(json.dumps(configuration, ensure_ascii=False, indent=2), encoding="utf-8")
        (output / "design.toml").write_text(design_text, encoding="utf-8")
        (output / "return_benchmarks.toml").write_bytes(benchmark.read_bytes())

    publication_path = output / "publication.json"
    if not publication_path.exists():
        publication = compute_factors(data_root=data_root, refresh_config=refresh,
            library=library, selected="all", start=design["start"], end=design["end"],
            artifact_root=output)
        publication_path.write_text(json.dumps(publication, indent=2), encoding="utf-8")
    statistics = output / "statistics"
    if not (statistics / "summary.json").exists():
        reuse_inputs(source=Path(design["peer_statistics"]), output=statistics,
                     battery=battery, as_of=design["end"])
        run_statistics(data_root=data_root, config=battery, library=library,
                       as_of=design["end"], output=statistics, workers=workers)
    screen = output / "screen"
    if not (screen / "summary.json").exists():
        run_screen(statistics=statistics, output=screen, library=library)
    screening = json.loads((screen / "summary.json").read_text(encoding="utf-8"))
    scope = json.loads(scope_text)["symbols"]
    coverage = pl.concat([monthly_coverage(
        pl.read_parquet(statistics / "factors" / d.id / "monthly_scores.parquet"),
        pl.read_parquet(statistics / "factors" / d.id / "monthly_ic.parquet"),
        symbols=scope, factor=d.id, variants=settings["variants"]) for d in definitions])
    coverage.write_parquet(output / "monthly_coverage.parquet")
    coverage.write_csv(output / "monthly_coverage.csv")
    coverage_summary = coverage.group_by("factor", "variant").agg(
        pl.len().alias("window_months"), pl.col("rank_ic").count().alias("valid_ic_months"),
        pl.col("valid_stocks").min().alias("minimum_valid_stocks"),
        pl.col("valid_stocks").median().alias("median_valid_stocks"),
        pl.col("universe_coverage").mean().alias("mean_universe_coverage"),
        pl.col("requested_coverage").mean().alias("mean_requested_coverage"),
    ).sort("factor", "variant").to_dicts()
    # Publish a real scorecard before the slower optional account replay.
    if not (output / "scorecard_statistics" / "summary.json").exists():
        run_scorecard(screen=screen, output=output / "scorecard_statistics", cost_runs=[],
            cost_root=None, benchmarks=None, redundancy=None, data_root=data_root,
            return_benchmark_config=output / "return_benchmarks.toml")
    result = {"scope": "numeric forecast baseline; no text scores or incremental-text claims",
        "start": str(design["start"]), "end": str(design["end"]),
        "requested_stocks": len(scope), "coverage": coverage_summary,
        "statistics": str(statistics), "scorecard": str(output / "scorecard_statistics"),
        "costs": None,
        "conclusion": "REJECTED" if screening["statistical_pass_rows"] == 0 else "RESEARCH_ONLY"}
    (output / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    if costs:
        cost_result = run_cost_batch(statistics=statistics, screen=screen, output=output / "costs",
            data_root=data_root, execution_snapshot=design["execution_snapshot"],
            existing_runs=[], workers=workers, resume=resume)
        scorecard = output / "scorecard_costs"
        suffix = 2
        while scorecard.exists():
            scorecard = output / f"scorecard_costs_{suffix:03d}"
            suffix += 1
        run_scorecard(screen=screen, output=scorecard,
            cost_runs=[Path(p) for p in cost_result["completed_runs"].values()],
            cost_root=None, benchmarks=None, redundancy=None, data_root=data_root,
            return_benchmark_config=output / "return_benchmarks.toml")
        result.update(costs=cost_result, scorecard=str(scorecard))
        (output / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path,
                        default=Path("configs/factors/p7_numeric_evaluation_20260912.toml"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--costs", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run_pipeline(config=args.config, output=args.output,
        data_root=args.data_root, workers=args.workers, costs=args.costs, resume=args.resume)), flush=True)


if __name__ == "__main__":
    main()
