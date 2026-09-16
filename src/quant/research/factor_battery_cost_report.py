"""Summarize saved daily cost runs and compare aligned benchmark windows."""
import argparse
import datetime as dt
import json
import math
import tomllib
from pathlib import Path

import numpy as np
import polars as pl

from quant.research.factor_battery_costs import cost_metrics
from quant.reporting.multifactor_assessment import holding_metrics


def compare_nav(strategy: pl.DataFrame, benchmark: pl.DataFrame) -> dict:
    """Rebase both series before the first common day, including that day's return."""
    for frame in (strategy, benchmark):
        if (frame.is_empty() or frame['date'].null_count() or not frame['date'].is_sorted()
                or frame['date'].n_unique() != frame.height
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
    if not parts[0]['date'].equals(parts[1]['date']):
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
        if year.is_dir() and year.name.isdigit():
            navs.append(pl.read_parquet(year/'nav.parquet'))
            trades.append(pl.read_parquet(year/'trades.parquet'))
    if not navs:
        raise ValueError('No cost history')
    nav = pl.concat(navs, how='vertical_relaxed')
    if nav['date'][-1] != end:
        raise ValueError('Cost history has not reached its configured end date')
    return nav, pl.concat(trades, how='vertical_relaxed')


REQUIRED_BENCHMARKS = {'510300_total_return_reference', 'csi800_equal_weight', 'all_market_equal_weight'}
MEASUREMENT = 'holding_window_return_indexes_v1'


def holding_cost_metrics(nav: pl.DataFrame, trades: pl.DataFrame, *, initial_cash: float) -> dict:
    measured = holding_metrics(nav, trades, initial_cash=initial_cash)
    start = measured['active_start']
    if start is None:
        return {**measured, 'holding_evidence': False, 'first_date': None,
                'last_date': str(nav['date'][-1]), 'ending_equity': nav['equity'][-1],
                'gross_traded_notional': 0., 'cumulative_fees': nav['cumulative_fees'][-1]}
    before = nav.filter(pl.col('date') < start)
    equity = before['equity'][-1] if before.height else initial_cash
    unit = before['unit_nav'][-1] if before.height else 1.
    fees = before['cumulative_fees'][-1] if before.height else 0.
    window = nav.filter(pl.col('date') >= start).with_columns(
        (pl.col('unit_nav')/unit).alias('unit_nav'),
        (pl.col('cumulative_fees')-fees).alias('cumulative_fees'))
    metrics = cost_metrics(window, trades.filter(pl.col('date') >= start), initial_cash=equity)
    return {**metrics, **measured, 'holding_evidence': True,
            'first_date': str(start), 'last_date': str(nav['date'][-1])}


def compare_holding_index(nav: pl.DataFrame, benchmark: pl.DataFrame, *, start: dt.date, end: dt.date) -> dict:
    """Require the entire holding window, never shrink to available index coverage."""
    if {'equity', 'market_value', 'cash'} & set(benchmark.columns):
        raise ValueError('Account replay cannot be used as a return index')
    pieces = []
    grid = nav.filter(pl.col('date').is_between(start, end))['date']
    for frame in (nav, benchmark):
        if frame.is_empty() or not frame['date'].is_sorted() or frame['date'].n_unique() != frame.height:
            raise ValueError('Index comparison requires ordered unique dates')
        part = frame.filter(pl.col('date').is_between(start, end))
        if not part['date'].equals(grid) or not len(grid) or grid[-1] != end:
            raise ValueError('Benchmark history is missing holding-window sessions; no shrinking')
        prior = frame.filter(pl.col('date') < start)
        anchor = prior['unit_nav'][-1] if prior.height else 1.
        pieces.append(part.select('date', (pl.col('unit_nav')/anchor).alias('unit_nav')))
    return compare_nav(*pieces)


def return_indexes(*, config: Path, data_root: Path, start: dt.date, end: dt.date,
                   cache: dict[tuple, pl.DataFrame], errors: dict[str, str] | None = None) -> dict[str, pl.DataFrame]:
    from quant.data.equal_weight_index import load_return_benchmarks

    result = {}
    key = (config.resolve(), config.read_bytes(), data_root.resolve(), start, end)
    for name in sorted(REQUIRED_BENCHMARKS):
        cache_key = (*key, name)
        try:
            if cache_key not in cache:
                source = '510300' if name == '510300_total_return_reference' else name
                loaded = load_return_benchmarks(config=config, data_root=data_root, start=start, end=end, names=[source])
                if set(loaded) != {source}:
                    raise ValueError('Index loader returned the wrong selected reference')
                cache[cache_key] = loaded[source]
            result[name] = cache[cache_key]
        except (ValueError, OSError) as exc:
            if errors is None:
                raise
            errors[name] = f'{type(exc).__name__}: {exc}'
    return result


def index_comparisons(nav: pl.DataFrame, *, row: dict, baselines: dict[str, pl.DataFrame],
                      errors: dict[str, str], end: dt.date) -> list[dict]:
    comparisons = []
    for name in sorted(REQUIRED_BENCHMARKS):
        metadata = {**{key: row[key] for key in ('factor', 'variant', 'cost_multiplier')},
                    'benchmark': name, 'first_date': str(row['active_start']), 'last_date': str(end),
                    'benchmark_cost_treatment': 'return_index_without_account_constraints'}
        try:
            if name not in baselines:
                raise ValueError(errors.get(name, 'Return index not configured or unavailable'))
            comparison = compare_holding_index(nav, baselines[name], start=row['active_start'], end=end)
            comparisons.append({**metadata, **comparison, 'comparison_status': 'complete'})
        except (ValueError, OSError) as exc:
            comparisons.append({**metadata, 'comparison_status': 'unavailable',
                                'net_cagr_excess': None, 'error': str(exc)})
    return comparisons


def collect_cost_report(*, run: Path, benchmarks: Path | None = None,
                        etf_reference: bool = False, data_root: Path = Path('data'),
                        benchmark_cache: dict[tuple, pl.DataFrame] | None = None,
                        return_benchmark_config: Path | None = None) -> dict:
    # Owned by this report or its scorecard call, never shared across runs.
    cache = benchmark_cache if benchmark_cache is not None else {}
    settings = tomllib.loads((run/'battery.toml').read_text(encoding='utf-8'))
    saved = json.loads((run/'summary.json').read_text(encoding='utf-8'))
    if benchmarks is not None:
        benchmark_settings = tomllib.loads((benchmarks/'battery.toml').read_text(encoding='utf-8'))
        for key in ('portfolio', 'costs', 'universe', 'run'):
            if settings[key] != benchmark_settings[key]:
                raise ValueError(f'Incompatible benchmark {key}')
        if saved['execution_snapshot'] != json.loads((benchmarks/'summary.json').read_text())['execution_snapshot']:
            raise ValueError('Strategy and benchmark use different execution data')
    rows, comparisons, histories = [], [], {}
    for row in saved['rows']:
        nav, trades = load_cost_history(run, row['variant'], row['cost_multiplier'], settings['run']['as_of'])
        histories[row['variant'], row['cost_multiplier']] = (nav, trades)
        measured = holding_cost_metrics(nav, trades, initial_cash=settings['portfolio']['initial_cash'])
        metadata = {name: row[name] for name in ('factor', 'variant', 'cost_multiplier')}
        rows.append({**metadata, **measured})
    for row in rows:
        if row['holding_evidence']:
            errors: dict[str, str] = {}
            baselines = return_indexes(config=return_benchmark_config, data_root=data_root,
                start=row['active_start'], end=settings['run']['as_of'], cache=cache, errors=errors) if return_benchmark_config else {}
            nav, _ = histories[row['variant'], row['cost_multiplier']]
            comparisons.extend(index_comparisons(nav, row=row, baselines=baselines, errors=errors, end=settings['run']['as_of']))
    return {'source_run': str(run), 'rows': rows, 'benchmark_comparisons': comparisons,
            'measurement': MEASUREMENT, 'return_indexes_complete': bool(comparisons) and all(r['comparison_status'] == 'complete' for r in comparisons)}



def report_costs(*, run: Path, output: Path, benchmarks: Path | None = None,
                 etf_reference: bool = False, data_root: Path = Path('data'),
                 return_benchmark_config: Path | None = None) -> dict:
    result = collect_cost_report(run=run, benchmarks=benchmarks, etf_reference=etf_reference, data_root=data_root, return_benchmark_config=return_benchmark_config)
    rows, comparisons = result['rows'], result['benchmark_comparisons']
    output.mkdir(parents=True, exist_ok=False)
    if return_benchmark_config is not None:
        (output/'return_benchmarks.toml').write_bytes(return_benchmark_config.read_bytes())
    pl.from_dicts(rows, infer_schema_length=None).write_parquet(output/'cost_metrics.parquet')
    if comparisons:
        pl.from_dicts(comparisons, infer_schema_length=None).write_parquet(output/'benchmark_comparisons.parquet')
    (output/'summary.json').write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')
    from quant.reporting.period_metrics import period_metrics, write_period_reports
    from quant.reporting.strategy_description import describe
    settings = tomllib.loads((run/'battery.toml').read_text(encoding='utf-8'))
    links = ['# 保存净值的年度与月度表现', '']
    cache = {}
    for row in rows:
        variant, multiplier = row['variant'], row['cost_multiplier']
        nav, _ = load_cost_history(run, variant, multiplier, settings['run']['as_of'])
        baselines = return_indexes(config=return_benchmark_config, data_root=data_root,
            start=row['active_start'], end=settings['run']['as_of'], cache=cache) if return_benchmark_config and row['active_start'] else {}
        relative = f'periods/{variant}_cost_{multiplier:g}'
        write_period_reports(output/relative, period_metrics(nav, baselines), describe(run/'config.toml', variant))
        links.append(f'- [{variant} · {multiplier:g}×]({relative}/report.md)')
    (output/'report.md').write_text('\n'.join(links)+'\n', encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--benchmarks', type=Path)
    parser.add_argument('--return-benchmark-config', type=Path)
    parser.add_argument('--etf-reference', action='store_true')
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    args = parser.parse_args()
    print(json.dumps(report_costs(run=args.run, output=args.output, benchmarks=args.benchmarks,
                                 etf_reference=args.etf_reference, data_root=args.data_root, return_benchmark_config=args.return_benchmark_config), default=str))


if __name__ == '__main__':
    main()
