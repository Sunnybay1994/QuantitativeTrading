"""One-command P7 statistics plus same-support incremental diagnostics."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import tomllib
import uuid

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
                 workers: int = 1, execution_snapshot: str | None = None,
                 peer_library: Path = Path('configs/factors/library'),
                 peer_statistics: Path | None = None,
                 existing_cost_runs: list[Path] | None = None, resume: bool = False,
                 return_benchmark_config: Path | None = None) -> dict:
    from quant.research.factor_battery_batch import run_statistics
    from quant.research.factor_battery_screen import run_screen
    from quant.research.factor_battery_scorecard import run_scorecard

    if workers < 1 or (not execution_snapshot and (peer_statistics or existing_cost_runs)):
        raise ValueError('Positive workers and an execution snapshot are required for full evaluation inputs')
    design = load_design(design_path)
    library = Path("configs/factors/p7_text_library")
    battery_text = (run/'battery.toml').read_text(encoding='utf-8')
    refresh = tomllib.loads(battery_text).get('data', {}).get('refresh_config')
    configuration = {'run': str(run.resolve()), 'scoring': (run/'run.json').read_text(encoding='utf-8'),
        'battery': battery_text, 'refresh_config': Path(refresh).read_text(encoding='utf-8') if refresh else None,
        'design': design_path.read_text(encoding='utf-8'), 'data_root': str(data_root.resolve()),
        'execution_snapshot': execution_snapshot,
        'text_library': {p.name: p.read_text(encoding='utf-8') for p in sorted(library.glob('*.toml'))},
        'peer_library': {p.name: p.read_text(encoding='utf-8') for p in sorted(peer_library.glob('*.toml'))}
                        if execution_snapshot else {},
        'peer_statistics': str(peer_statistics.resolve()) if peer_statistics else None,
        'existing_cost_runs': sorted(str(p.resolve()) for p in existing_cost_runs or [])}
    saved_config = output/'pipeline_config.json'
    return_text = return_benchmark_config.read_text(encoding='utf-8') if return_benchmark_config is not None else None
    if return_text is not None:
        configuration['return_benchmarks'] = return_text
        tomllib.loads(return_text)['benchmarks']
    if resume:
        if not saved_config.is_file() or json.loads(saved_config.read_text(encoding='utf-8')) != configuration:
            raise ValueError('Resume requires the same scoring run, design and evaluation inputs')
        if (output/'summary.json').is_file():
            previous = json.loads((output/'summary.json').read_text(encoding='utf-8'))
            prior_costs = previous['costs']
            if not prior_costs or not (prior_costs['failures'] or prior_costs['pending_external_runs']):
                return previous
    else:
        output.mkdir(parents=True, exist_ok=False)
        saved_config.write_text(json.dumps(configuration, indent=2), encoding='utf-8')
    if return_text is not None:
        return_benchmark_config = output/'return_benchmarks.toml'
        return_benchmark_config.write_text(return_text, encoding='utf-8')

    def stage(folder: Path, action, *, resumable: bool = False):
        if resume and (folder/'summary.json').is_file():
            return json.loads((folder/'summary.json').read_text(encoding='utf-8'))
        if folder.exists() and not resumable:
            preserved = folder.with_name(f'{folder.name}_partial_{uuid.uuid4().hex[:8]}')
            if not folder.resolve().is_relative_to(output.resolve()) or not preserved.resolve().is_relative_to(output.resolve()):
                raise ValueError('Partial output must stay inside the evaluation directory')
            folder.rename(preserved)
        return action()

    publication_path = output/'publication.json'
    if resume and publication_path.is_file():
        publication = json.loads(publication_path.read_text(encoding='utf-8'))
    else:
        publication = publish_panels(run, data_root=data_root, design=design)
        publication_path.write_text(json.dumps(publication, indent=2), encoding='utf-8')
    statistics = output / "statistics"
    stage(statistics, lambda: run_statistics(data_root=data_root, config=run / "battery.toml", library=library,
                   as_of=design["end"], output=statistics, workers=workers), resumable=True)
    screen = stage(output/'screen', lambda: run_screen(statistics=statistics, output=output / "screen", library=library))
    incremental = stage(output/'incremental', lambda: run_incremental(run=run, statistics=statistics, data_root=data_root,
                                  output=output / "incremental", design=design))
    costs = None
    redundancy = benchmarks = None
    if execution_snapshot:
        from quant.research.factor_battery_cost_batch import run_cost_batch
        from quant.research.factor_battery_benchmarks import run_benchmarks
        from quant.research.forecast_text_redundancy import run_redundancy

        if peer_statistics is None:
            peer_statistics = output / 'peer_statistics'
            stage(peer_statistics, lambda: run_statistics(data_root=data_root, config=run / 'battery.toml', library=peer_library,
                           as_of=design['end'], output=peer_statistics, workers=workers), resumable=True)
        redundancy = output / 'redundancy'
        stage(redundancy, lambda: run_redundancy(statistics=statistics, peer_statistics=peer_statistics,
                       peer_library=peer_library, output=redundancy, workers=workers))
        benchmarks = output / 'benchmarks'
        stage(benchmarks, lambda: run_benchmarks(statistics=statistics, output=benchmarks, data_root=data_root,
                       execution_snapshot=execution_snapshot))
        costs = run_cost_batch(statistics=statistics, screen=output / "screen", output=output / "costs",
            data_root=data_root, execution_snapshot=execution_snapshot,
            existing_runs=existing_cost_runs or [], workers=workers, resume=resume)
    scorecard_output = output/'scorecard'
    number = 2
    while scorecard_output.exists():
        scorecard_output = output/f'scorecard_{number:03d}'
        number += 1
    scorecard = run_scorecard(screen=output / 'screen', output=scorecard_output,
        cost_runs=[Path(path) for path in costs['completed_runs'].values()] if costs else [],
        cost_root=None, benchmarks=benchmarks, redundancy=redundancy, data_root=data_root,
        return_benchmark_config=return_benchmark_config)
    summary = {"synthetic_fixture": False, "publication": publication, "screen": screen,
        "incremental_series": len(incremental["summary"]), "costs": costs,
        "mode": "full" if execution_snapshot else "statistics_only",
        "scorecard": scorecard, "scorecard_path": str(scorecard_output/'factor_scorecard.parquet'),
        "peer_statistics": str(peer_statistics) if peer_statistics else None,
        "conclusion": "RESEARCH_ONLY",
        "next_step": ("Inspect scorecard and unresolved evidence; residual IC remains diagnostic"
                      if execution_snapshot else "Supply an execution snapshot for full costs, benchmarks and cross-library comparison")}
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
    parser.add_argument('--peer-library', type=Path, default=Path('configs/factors/library'))
    parser.add_argument('--peer-statistics', type=Path, help='Existing complete peer statistics with identical P7 settings')
    parser.add_argument('--existing-cost-run', type=Path, action='append', default=[])
    parser.add_argument('--resume', action='store_true', help='Continue the same evaluation after its previous process stops')
    parser.add_argument('--return-benchmark-config', type=Path)
    args = parser.parse_args()
    if args.fixture:
        if args.resume:
            parser.error('--resume applies to real scoring runs, not synthetic fixtures')
        result = run_fixture(source=args.fixture, output=args.output, design_path=args.design)
    else:
        result = run_pipeline(run=args.run, output=args.output, data_root=args.data_root,
            design_path=args.design, workers=args.workers, execution_snapshot=args.execution_snapshot,
            peer_library=args.peer_library, peer_statistics=args.peer_statistics,
            existing_cost_runs=args.existing_cost_run, resume=args.resume,
            return_benchmark_config=args.return_benchmark_config)
    print(json.dumps(result, default=str, ensure_ascii=False))
    costs = result.get('costs')
    if costs and (costs['failures'] or costs['pending_external_runs']):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
