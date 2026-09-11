"""Annual training cost screens from completed, causally truncated replay histories."""
import argparse
import datetime as dt
import json
import tomllib
from pathlib import Path

import polars as pl

from quant.data.factor_benchmarks import read_etf_total_return
from quant.research.factor_battery_cost_batch import existing_cost_factor
from quant.research.factor_battery_cost_report import compare_nav, load_cost_history
from quant.research.factor_battery_costs import cost_metrics
from quant.research.factor_battery_scorecard import assemble_scorecard


def prefix_cost_report(*, factor: str, histories: dict, benchmarks: dict,
                       cutoff: dt.date, initial_cash: float) -> dict:
    """Recompute every metric; never carry full-period summary fields into a fit."""
    rows, comparisons = [], []
    for (variant, multiplier), (full_nav, full_trades) in histories.items():
        nav = full_nav.filter(pl.col('date') <= cutoff)
        if nav.is_empty():
            continue
        if nav['date'][-1] != cutoff:
            raise ValueError('Cost history is missing the refit session')
        trades = full_trades.filter(pl.col('date') <= cutoff)
        metadata = {'factor': factor, 'variant': variant, 'cost_multiplier': multiplier}
        rows.append({**metadata, 'first_date': str(nav['date'][0]), 'last_date': str(cutoff),
                     **cost_metrics(nav, trades, initial_cash=initial_cash)})
        for (name, cost), full_baseline in benchmarks.items():
            if cost is not None and cost != multiplier:
                continue
            baseline = full_baseline.filter(pl.col('date') <= cutoff)
            if baseline.is_empty():
                continue
            if baseline['date'][-1] != cutoff:
                raise ValueError('Benchmark history is missing the refit session')
            comparisons.append({**metadata, 'benchmark': name, **compare_nav(nav, baseline)})
    return {'rows': rows, 'benchmark_comparisons': comparisons}


def run_cost_prefixes(*, prefix: Path, output: Path, cost_runs: list[Path],
                      cost_root: Path, benchmarks: Path, data_root: Path) -> dict:
    settings = tomllib.loads((prefix/'battery.toml').read_text(encoding='utf-8'))
    benchmark_settings = tomllib.loads((benchmarks/'battery.toml').read_text(encoding='utf-8'))
    for key in ('portfolio', 'costs', 'universe', 'run', 'data'):
        if settings[key] != benchmark_settings[key]:
            raise ValueError(f'Incompatible benchmark {key}')
    benchmark_summary = json.loads((benchmarks/'summary.json').read_text(encoding='utf-8'))
    end = settings['run']['as_of']
    baseline = {(row['variant'], row['cost_multiplier']): load_cost_history(
        benchmarks, row['variant'], row['cost_multiplier'], end)[0] for row in benchmark_summary['rows']}
    baseline[('510300_total_return_reference', None)] = read_etf_total_return(
        data_root=data_root, snapshot=settings['data']['etf_total_return_snapshot'], end=end)
    screens = pl.read_parquet(prefix/'annual_statistical_screen.parquet')
    annual = {key[0]: frame for key, frame in screens.partition_by('test_year', as_dict=True).items()}
    reports: dict[int, list] = {year: [] for year in annual}
    sources = {}
    for run in [*cost_runs, *sorted(p.parent for p in cost_root.glob('*/summary.json'))]:
        if not (run/'summary.json').is_file():
            continue
        factor = existing_cost_factor(run, settings=settings, snapshot=benchmark_summary['execution_snapshot'])
        if factor in sources:
            raise ValueError('Duplicate factor cost history')
        sources[factor] = str(run)
        saved = json.loads((run/'summary.json').read_text(encoding='utf-8'))
        histories = {(row['variant'], row['cost_multiplier']): load_cost_history(
            run, row['variant'], row['cost_multiplier'], end) for row in saved['rows']}
        for year, table in annual.items():
            cutoffs = table['refit_close'].unique().to_list()
            if len(cutoffs) != 1:
                raise ValueError('One refit close required per annual screen')
            report = prefix_cost_report(factor=factor, histories=histories, benchmarks=baseline,
                cutoff=cutoffs[0], initial_cash=settings['portfolio']['initial_cash'])
            if report['rows']:
                reports[year].append(report)
    tables, counts, metrics, comparisons = [], [], [], []
    for year, table in annual.items():
        result = assemble_scorecard(table, cost_reports=reports[year], correlations=None, settings=settings).drop(
            'factor_admitted', 'redundancy_pass').with_columns(
                (pl.col('statistical_pass') & pl.col('costs_complete') & pl.col('cost_excess_pass')).alias(
                    'statistics_and_cost_pass'))
        tables.append(result)
        primary = result.filter(pl.col('variant') == settings['primary_variant'])
        counts.append({'test_year': year, 'primary_statistics_and_cost_pass':
            primary['statistics_and_cost_pass'].fill_null(False).sum(),
            'primary_statistics_pass_cost_missing': primary.filter(
                pl.col('statistical_pass') & (~pl.col('costs_complete') | pl.col('cost_excess_pass').is_null())).height})
        for report in reports[year]:
            metrics.extend({**row, 'test_year': year} for row in report['rows'])
            comparisons.extend({**row, 'test_year': year} for row in report['benchmark_comparisons'])
    summary = {'complete_cost_factors': len(sources), 'annual_screens': counts, 'source_runs': sources,
               'scope': 'training statistics and costs; annual correlations still required before selection'}
    output.mkdir(parents=True, exist_ok=False)
    for name in ('battery.toml', 'model.toml'):
        (output/name).write_bytes((prefix/name).read_bytes())
    pl.concat(tables, how='diagonal_relaxed').write_parquet(output/'annual_cost_screen.parquet')
    if metrics:
        pl.from_dicts(metrics, infer_schema_length=None).write_parquet(output/'annual_cost_metrics.parquet')
    if comparisons:
        pl.from_dicts(comparisons, infer_schema_length=None).write_parquet(output/'annual_benchmark_comparisons.parquet')
    (output/'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cost-run', type=Path, action='append', default=[])
    parser.add_argument('--cost-root', type=Path, required=True)
    parser.add_argument('--benchmarks', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    args = parser.parse_args()
    print(json.dumps(run_cost_prefixes(prefix=args.prefix, output=args.output, cost_runs=args.cost_run,
        cost_root=args.cost_root, benchmarks=args.benchmarks, data_root=args.data_root)))


if __name__ == '__main__':
    main()
