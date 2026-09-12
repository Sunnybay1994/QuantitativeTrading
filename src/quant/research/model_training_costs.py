"""Annual training cost screens from completed, causally truncated replay histories."""
import argparse
import datetime as dt
import json
import tomllib
from pathlib import Path
from typing import cast

import polars as pl

from quant.research.factor_battery_cost_batch import existing_cost_factor
from quant.research.factor_battery_cost_report import (
    MEASUREMENT, holding_cost_metrics, index_comparisons,
    load_cost_history, return_indexes,
)
from quant.research.factor_battery_scorecard import assemble_scorecard
from quant.research.model_training_prefix import training_prefix_settings


def prefix_cost_report(*, factor: str, histories: dict, benchmarks: dict,
                       cutoff: dt.date, initial_cash: float, benchmark_errors: dict[str, str] | None = None) -> dict:
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
        measured = holding_cost_metrics(nav, trades, initial_cash=initial_cash)
        rows.append({**metadata, **measured})
        if not measured['holding_evidence']:
            continue
        if any(cost is not None for name, cost in benchmarks):
            raise ValueError('Costed account benchmarks cannot enter annual index comparison')
        baselines = {name: frame.filter(pl.col('date') <= cutoff) for (name, _), frame in benchmarks.items()}
        comparisons.extend(index_comparisons(nav, row={**metadata, **measured}, baselines=baselines,
                                            errors=benchmark_errors or {}, end=cutoff))
    return {'rows': rows, 'benchmark_comparisons': comparisons, 'measurement': MEASUREMENT,
            'return_indexes_complete': bool(comparisons) and all(row['comparison_status'] == 'complete' for row in comparisons)}


def run_cost_prefixes(*, prefix: Path, output: Path, cost_runs: list[Path],
                      cost_root: Path, benchmarks: Path, data_root: Path,
                      return_benchmark_config: Path | None = None) -> dict:
    if return_benchmark_config is None:
        raise ValueError('Annual cost screening requires explicit return_benchmark_config')
    settings = tomllib.loads((prefix/'battery.toml').read_text(encoding='utf-8'))
    model = tomllib.loads((prefix/'model.toml').read_text(encoding='utf-8'))
    training_settings = training_prefix_settings(settings, model)
    if (prefix/'summary.json').is_file():
        prefix_summary = json.loads((prefix/'summary.json').read_text(encoding='utf-8'))
        if prefix_summary.get('training_minimum_months', training_settings['admission']['minimum_months']) != training_settings['admission']['minimum_months']:
            raise ValueError('Annual statistical prefix threshold differs from the model configuration')
    benchmark_settings = tomllib.loads((benchmarks/'battery.toml').read_text(encoding='utf-8'))
    for key in ('portfolio', 'costs', 'universe', 'run', 'data'):
        if settings[key] != benchmark_settings[key]:
            raise ValueError(f'Incompatible benchmark {key}')
    benchmark_summary = json.loads((benchmarks/'summary.json').read_text(encoding='utf-8'))
    end = settings['run']['as_of']
    benchmark_cache: dict[tuple, pl.DataFrame] = {}
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
            for history_key, history in histories.items():
                active = history[0].filter((pl.col('market_value') > 0) & (pl.col('date') <= cutoffs[0]))
                errors: dict[str, str] = {}
                loaded = return_indexes(config=return_benchmark_config, data_root=data_root,
                    start=cast(dt.date, active['date'].min()), end=cutoffs[0], cache=benchmark_cache,
                    errors=errors) if active.height else {}
                baseline = {(name, None): frame for name, frame in loaded.items()}
                report = prefix_cost_report(factor=factor, histories={history_key: history}, benchmarks=baseline,
                    cutoff=cutoffs[0], initial_cash=settings['portfolio']['initial_cash'], benchmark_errors=errors)
                if report['rows']:
                    reports[year].append(report)
    tables, counts = [], []
    metrics: list[dict] = []
    comparisons: list[dict] = []
    for year, table in annual.items():
        result = assemble_scorecard(table, cost_reports=reports[year], correlations=None, settings=training_settings).drop(
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
               'measurement': MEASUREMENT, 'final_battery_minimum_months': settings['admission']['minimum_months'],
               'training_minimum_months': training_settings['admission']['minimum_months'],
               'scope': 'refit-close holding-window statistics and return-index cost comparisons; annual correlations still required'}
    output.mkdir(parents=True, exist_ok=False)
    (output/'return_benchmarks.toml').write_bytes(return_benchmark_config.read_bytes())
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
    parser.add_argument('--return-benchmark-config', type=Path, required=True)
    parser.add_argument('--benchmarks', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    args = parser.parse_args()
    print(json.dumps(run_cost_prefixes(prefix=args.prefix, output=args.output, cost_runs=args.cost_run,
        cost_root=args.cost_root, benchmarks=args.benchmarks, data_root=args.data_root,
        return_benchmark_config=args.return_benchmark_config)))


if __name__ == '__main__':
    main()
