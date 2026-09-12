"""Join battery evidence without turning missing costs or correlations into passes."""
import argparse
import json
import math
import tomllib
from pathlib import Path

import polars as pl

from quant.research.factor_battery_cost_batch import existing_cost_factor
from quant.research.factor_battery_cost_report import collect_cost_report


def assemble_scorecard(screen: pl.DataFrame, *, cost_reports: list[dict],
                       correlations: pl.DataFrame | None, settings: dict) -> pl.DataFrame:
    keys = screen.select('factor', 'variant').rows()
    if len(keys) != len(set(keys)):
        raise ValueError('Duplicate scorecard factor/variant rows')
    extras: dict[tuple, dict] = {key: {} for key in keys}
    primary = screen.filter(pl.col('variant') == settings['primary_variant']).with_columns(pl.col('icir').fill_nan(None)).sort(
        ['icir', 'factor'], descending=[True, False], nulls_last=True)['factor'].to_list()
    seen = set()
    for report in cost_reports:
        factors = {row['factor'] for row in report['rows']}
        if len(factors) != 1:
            raise ValueError('A cost report must refer to one factor')
        factor = next(iter(factors))
        for row in report['rows']:
            key = (factor, row['variant'])
            identity = (*key, row['cost_multiplier'])
            if key not in extras or identity in seen:
                raise ValueError('Unknown or duplicate cost result')
            seen.add(identity)
            prefix = f"cost_{row['cost_multiplier']:g}".replace('.', 'p')
            for metric in ('cagr', 'sharpe', 'max_drawdown', 'annualized_one_way_turnover', 'mean_invested_fraction'):
                extras[key][f'{prefix}_{metric}'] = row[metric]
        for row in report['benchmark_comparisons']:
            key = (factor, row['variant'])
            prefix = f"cost_{row['cost_multiplier']:g}".replace('.', 'p')
            extras[key][f"{prefix}_{row['benchmark']}_cagr_excess"] = row['net_cagr_excess']
    if correlations is not None:
        correlation_keys = correlations.select('factor', 'variant').rows()
        if len(correlation_keys) != len(keys) or set(correlation_keys) != set(keys):
            raise ValueError('Require the complete correlation maxima table')
        if 'comparison_primary_rank' in correlations.columns:
            ranks = correlations.select('factor', 'comparison_primary_rank').unique()
            values = ranks['comparison_primary_rank'].to_list()
            if (ranks.height != screen['factor'].n_unique()
                    or any(type(value) is not int or value < 0 for value in values)
                    or len(set(values)) != len(values)):
                raise ValueError('Invalid comparison-pool primary ranks')
        for row in correlations.iter_rows(named=True):
            extras[(row['factor'], row['variant'])].update({k: v for k, v in row.items() if k not in ('factor', 'variant')})
    rows = []
    for row in screen.iter_rows(named=True):
        extra = extras[(row['factor'], row['variant'])]
        costs_ready = all(extra.get(f"cost_{mult:g}_cagr".replace('.', 'p')) is not None
                          for mult in settings['portfolio']['cost_multipliers'])
        excess = extra.get('cost_1_all_market_equal_weight_cagr_excess')
        cost_pass = excess > settings['admission']['minimum_top_net_excess_all_market_ew'] if excess is not None and math.isfinite(excess) else None
        rho = extra.get('higher_max_absolute_rank_correlation')
        redundancy_pass = (rho < settings['admission']['maximum_absolute_rank_correlation_with_better']
                           if rho is not None and math.isfinite(rho) else None)
        # The first factor in the complete primary ordering has no higher peer.
        # Its admission need not wait for unrelated all-peer diagnostics.
        comparison_rank = extra.get('comparison_primary_rank')
        highest = row['factor'] == primary[0] if comparison_rank is None else comparison_rank == 0
        if highest:
            redundancy_pass = True
        admitted = None
        if not row['statistical_pass'] or cost_pass is False or redundancy_pass is False:
            admitted = False
        elif costs_ready and cost_pass is True and redundancy_pass is True:
            admitted = True
        rows.append({**row, **extra, 'costs_complete': costs_ready, 'cost_excess_pass': cost_pass,
                     'redundancy_pass': redundancy_pass, 'factor_admitted': admitted,
                     'conclusion': 'REJECTED' if not row['statistical_pass'] else 'RESEARCH_ONLY'})
    return pl.from_dicts(rows, infer_schema_length=None).sort('factor', 'variant')


def run_scorecard(*, screen: Path, output: Path, cost_runs: list[Path], cost_root: Path | None,
                  benchmarks: Path | None, redundancy: Path | None, data_root: Path,
                  previous_scorecard: Path | None = None) -> dict:
    config = (screen/'battery.toml').read_bytes()
    settings = tomllib.loads(config.decode('utf-8'))
    statistics = pl.read_parquet(screen/'statistical_screen.parquet')
    runs = list(cost_runs)
    if previous_scorecard is not None:
        if (previous_scorecard/'battery.toml').read_bytes() != config:
            raise ValueError('Previous scorecard settings differ from the screen')
        previous = json.loads((previous_scorecard/'summary.json').read_text(encoding='utf-8'))
        prior_runs = [Path(path) for path in previous['cost_runs']]
        if any(not (path/'summary.json').is_file() for path in prior_runs):
            raise ValueError('A previous completed cost run is missing')
        runs.extend(prior_runs)
    if cost_root:
        runs.extend(path.parent for path in sorted(cost_root.glob('*/summary.json')))
    runs = list({path.resolve(): path for path in runs}.values())
    reports, paths = [], []
    benchmark_cache: dict[tuple, pl.DataFrame] = {}
    if benchmarks is not None and not (benchmarks/'summary.json').is_file():
        benchmarks = None
    snapshot = None
    factors_seen: set[str] = set()
    for run in runs:
        if not (run/'summary.json').is_file():
            continue
        saved = json.loads((run/'summary.json').read_text())
        if snapshot is not None and saved['execution_snapshot'] != snapshot:
            raise ValueError('Cost runs use different execution inputs')
        snapshot = saved['execution_snapshot']
        factor = existing_cost_factor(run, settings=settings, snapshot=snapshot)
        if factor in factors_seen:
            raise ValueError(f'Different completed cost runs for the same factor: {factor}')
        factors_seen.add(factor)
        reports.append(collect_cost_report(run=run, benchmarks=benchmarks, etf_reference=True,
                                          data_root=data_root, benchmark_cache=benchmark_cache))
        paths.append(str(run))
    correlation_table = None
    if redundancy is not None and (redundancy/'correlation_maxima.parquet').is_file():
        if (redundancy/'battery.toml').read_bytes() != config:
            raise ValueError('Correlation settings differ from the screen')
        correlation_table = pl.read_parquet(redundancy/'correlation_maxima.parquet')
    result = assemble_scorecard(statistics, cost_reports=reports, correlations=correlation_table, settings=settings)
    summary = {'rows': result.height, 'statistical_pass_rows': result['statistical_pass'].sum(),
               'cost_complete_rows': result['costs_complete'].sum(),
               'admitted_rows': result['factor_admitted'].fill_null(False).sum(),
               'admission_unresolved_rows': result['factor_admitted'].null_count(),
               'correlations_complete': correlation_table is not None,
               'stock_benchmarks_complete': benchmarks is not None,
               'cost_runs': paths}
    output.mkdir(parents=True, exist_ok=False)
    (output/'battery.toml').write_bytes(config)
    result.write_parquet(output/'factor_scorecard.parquet')
    (output/'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    diagnostic = (
        f"# 因子评分表：{settings['run']['as_of']}\n\n"
        f"共{result.height}个版本结果，{summary['statistical_pass_rows']}个通过统计门槛；"
        f"{summary['cost_complete_rows']}个已有三档成本，{summary['admitted_rows']}个证据齐全并通过因子准入。\n\n"
        f"尚有{summary['admission_unresolved_rows']}个统计候选版本缺少准入证据。"
        f"股票等权基准完成：{summary['stock_benchmarks_complete']}；"
        f"全库相关性完成：{summary['correlations_complete']}。\n\n"
        "下一步继续成本批处理、同区间基准比较和相关性计算，再生成新版本评分表。"
        "factor_admitted为空表示证据尚不完整；RESEARCH_ONLY因子仍须通过组合级验证。\n")
    (output/f"诊断_{settings['run']['as_of']}.md").write_text(diagnostic, encoding='utf-8')
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--screen', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cost-run', type=Path, action='append', default=[])
    parser.add_argument('--cost-root', type=Path)
    parser.add_argument('--previous-scorecard', type=Path,
                        help='Retain completed cost runs from a prior scorecard when collecting new results')
    parser.add_argument('--benchmarks', type=Path)
    parser.add_argument('--redundancy', type=Path)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    args = parser.parse_args()
    print(json.dumps(run_scorecard(screen=args.screen, output=args.output, cost_runs=args.cost_run,
                                  cost_root=args.cost_root, benchmarks=args.benchmarks,
                                  redundancy=args.redundancy, data_root=args.data_root,
                                  previous_scorecard=args.previous_scorecard)))


if __name__ == '__main__':
    main()
