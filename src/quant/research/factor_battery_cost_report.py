"""Summarize saved daily cost runs and compare aligned benchmark windows."""
import argparse
import json
import math
import tomllib
from pathlib import Path

import numpy as np
import polars as pl

from quant.research.factor_battery_costs import cost_metrics


def compare_nav(strategy: pl.DataFrame, benchmark: pl.DataFrame) -> dict:
    """Rebase both series before the first common day, including that day's return."""
    for frame in (strategy, benchmark):
        if (frame.is_empty() or frame['date'].to_list() != sorted(set(frame['date']))
                or not frame['unit_nav'].is_finite().all() or (frame['unit_nav'] <= 0).any()):
            raise ValueError('Comparison requires positive, ordered NAV histories')
    first = max(strategy['date'][0], benchmark['date'][0])
    last = min(strategy['date'][-1], benchmark['date'][-1])
    if first > last:
        raise ValueError('No common benchmark window')
    parts, values = [], []
    for frame in (strategy, benchmark):
        part = frame.filter(pl.col('date').is_between(first, last))
        earlier = frame.filter(pl.col('date') < first)['unit_nav']
        anchor = earlier[-1] if len(earlier) else 1.
        parts.append(part)
        values.append(part['unit_nav'].to_numpy()/anchor)
    if parts[0]['date'].to_list() != parts[1]['date'].to_list():
        raise ValueError('Benchmark has a different session grid')
    size = len(values[0])
    strategy_cagr, benchmark_cagr = [float(v[-1]**(252/size)-1) for v in values]
    daily = [np.diff(np.r_[1., v])/np.r_[1., v][:-1] for v in values]
    active = daily[0]-daily[1]
    deviation = float(np.std(active, ddof=1)) if size > 1 else 0.
    return {'first_date': str(first), 'last_date': str(last), 'sessions': size,
            'strategy_cagr': strategy_cagr, 'benchmark_cagr': benchmark_cagr,
            'net_cagr_excess': strategy_cagr-benchmark_cagr,
            'relative_total_return': float(values[0][-1]/values[1][-1]-1),
            'information_ratio': float(np.mean(active)/deviation*math.sqrt(252)) if deviation > 1e-12 else None}


def load_cost_history(run: Path, variant: str, multiplier: float, end) -> tuple[pl.DataFrame, pl.DataFrame]:
    if not (run/'summary.json').is_file():
        raise ValueError('Finish the cost run before reporting')
    folder = run/variant/f'cost_{multiplier:g}'
    navs, trades = [], []
    for year in sorted(folder.iterdir()):
        if year.is_dir():
            navs.append(pl.read_parquet(year/'nav.parquet'))
            trades.append(pl.read_parquet(year/'trades.parquet'))
    if not navs:
        raise ValueError('No cost history')
    nav = pl.concat(navs, how='vertical_relaxed')
    if nav['date'][-1] != end:
        raise ValueError('Cost history has not reached its configured end date')
    return nav, pl.concat(trades, how='vertical_relaxed')


def report_costs(*, run: Path, output: Path, benchmarks: Path | None = None) -> dict:
    settings = tomllib.loads((run/'battery.toml').read_text(encoding='utf-8'))
    saved = json.loads((run/'summary.json').read_text(encoding='utf-8'))
    benchmark_rows = []
    if benchmarks is not None:
        benchmark_settings = tomllib.loads((benchmarks/'battery.toml').read_text(encoding='utf-8'))
        for key in ('portfolio', 'costs', 'universe', 'run'):
            if settings[key] != benchmark_settings[key]:
                raise ValueError(f'Incompatible benchmark {key}')
        if saved['execution_snapshot'] != json.loads((benchmarks/'summary.json').read_text())['execution_snapshot']:
            raise ValueError('Strategy and benchmark use different execution data')
        benchmark_rows = json.loads((benchmarks/'summary.json').read_text())['rows']
    rows, comparisons = [], []
    for row in saved['rows']:
        nav, trades = load_cost_history(run, row['variant'], row['cost_multiplier'], settings['run']['as_of'])
        rows.append({**row, **cost_metrics(nav, trades, initial_cash=settings['portfolio']['initial_cash'])})
        for benchmark in benchmark_rows:
            if benchmark['cost_multiplier'] != row['cost_multiplier']:
                continue
            baseline, _ = load_cost_history(benchmarks, benchmark['variant'], benchmark['cost_multiplier'],
                                            settings['run']['as_of'])
            comparisons.append({'variant': row['variant'], 'cost_multiplier': row['cost_multiplier'],
                                'benchmark': benchmark['variant'], **compare_nav(nav, baseline)})
    result = {'source_run': str(run), 'rows': rows, 'benchmark_comparisons': comparisons}
    output.mkdir(parents=True, exist_ok=False)
    pl.from_dicts(rows, infer_schema_length=None).write_parquet(output/'cost_metrics.parquet')
    if comparisons:
        pl.from_dicts(comparisons, infer_schema_length=None).write_parquet(output/'benchmark_comparisons.parquet')
    (output/'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--benchmarks', type=Path)
    args = parser.parse_args()
    print(json.dumps(report_costs(run=args.run, output=args.output, benchmarks=args.benchmarks)))


if __name__ == '__main__':
    main()
