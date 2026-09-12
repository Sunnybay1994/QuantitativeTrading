"""Compare corrected model runs on their own holding windows and a common window."""
import argparse
import datetime as dt
import json
import tomllib
from pathlib import Path

import polars as pl

from quant.data.equal_weight_index import load_return_benchmarks
from quant.reporting.cycle_stress import path_statistics
from quant.research.factor_battery_cost_report import load_cost_history


def window_metrics(nav: pl.DataFrame, trades: pl.DataFrame, *, start: dt.date,
                   end: dt.date, initial_cash: float) -> dict:
    """Keep prior-day capital, the first day's return, and all subsequent cash."""
    if (not nav['date'].is_sorted() or nav['date'].n_unique() != nav.height
            or nav['date'].null_count() or initial_cash <= 0):
        raise ValueError('Require ordered unique NAV and positive initial capital')
    window = nav.filter(pl.col('date').is_between(start, end))
    if window.is_empty() or window['date'][0] != start or window['date'][-1] != end:
        raise ValueError('Require the full requested comparison window')
    if trades.filter(~pl.col('date').is_in(nav['date'].implode())).height:
        raise ValueError('Trades fall outside saved NAV')
    prior = nav.select('date', pl.col('equity').shift(1).fill_null(initial_cash).alias('prior_equity'))
    if prior.filter(~pl.col('prior_equity').is_finite() | (pl.col('prior_equity') <= 0)).height:
        raise ValueError('Invalid prior capital')
    amounts = trades.filter(pl.col('date').is_between(start, end)).group_by('date').agg(pl.col('notional').sum())
    daily = prior.filter(pl.col('date').is_between(start, end)).join(amounts, on='date', how='left')
    turnover = daily.select((pl.col('notional').fill_null(0)/(2*pl.col('prior_equity'))).sum()).item()
    return {**path_statistics(nav, start=start, end=end),
        'annualized_one_way_turnover': turnover*252/window.height,
        'cash_sessions': window.filter(pl.col('market_value') == 0).height}


def compare(*, baseline: Path, candidate: Path, measurement_config: Path,
            output: Path, data_root: Path) -> dict:
    roots = {'baseline': baseline, 'candidate': candidate}
    models, metrics = {}, {}
    for name, root in roots.items():
        if (root/'reports/measurement.toml').read_bytes() != measurement_config.read_bytes():
            raise ValueError('Both completed reports must use the requested measurement')
        models[name] = tomllib.loads((root/'predictions/model.toml').read_text(encoding='utf-8'))
        metrics[name] = pl.read_parquet(root/'reports/cost_metrics.parquet')
    if models['baseline']['portfolio'] != models['candidate']['portfolio']:
        raise ValueError('Keep portfolio and cost parameters unchanged')
    keys = ['variant', 'cost_multiplier']
    if not metrics['baseline'].select(keys).sort(keys).equals(metrics['candidate'].select(keys).sort(keys)):
        raise ValueError('Require identical model and cost scenarios')
    end = models['baseline']['walk_forward']['test_end']
    if models['candidate']['walk_forward']['test_end'] != end:
        raise ValueError('Require the same registered end date')
    common_rows, benchmark_rows, own_rows = [], [], []
    cache = {}
    for case in metrics['baseline'].select(keys).to_dicts():
        own = {name: frame.filter((pl.col('variant') == case['variant'])
            & (pl.col('cost_multiplier') == case['cost_multiplier'])).to_dicts()[0]
            for name, frame in metrics.items()}
        if any(row['active_start'] is None for row in own.values()):
            raise ValueError('A common holding comparison needs stock holdings in both models')
        start = max(dt.date.fromisoformat(str(row['active_start'])) for row in own.values())
        if start not in cache:
            cache[start] = load_return_benchmarks(config=measurement_config, data_root=data_root, start=start, end=end)
        grid = None
        for name, root in roots.items():
            nav, trades = load_cost_history(root/'replay', case['variant'], case['cost_multiplier'], end)
            observed = nav.filter(pl.col('date').is_between(start, end))['date'].to_list()
            if grid is not None and observed != grid:
                raise ValueError('Models have different session grids')
            grid = observed
            measured = window_metrics(nav, trades, start=start, end=end,
                initial_cash=models[name]['portfolio']['initial_cash'])
            common_rows.append({'model': name, **case, **measured})
            own_rows.append({'model': name, **own[name]})
        for name, frame in cache[start].items():
            if frame['date'].to_list() != grid:
                raise ValueError('Benchmark does not cover the full common window')
            benchmark_rows.append({'benchmark': name, **case, **path_statistics(frame, start=start, end=end)})
    output.mkdir(parents=True, exist_ok=False)
    pl.from_dicts(common_rows).write_parquet(output/'common_metrics.parquet')
    pl.from_dicts(own_rows).write_parquet(output/'own_holding_metrics.parquet')
    pl.from_dicts(benchmark_rows).write_parquet(output/'common_benchmarks.parquet')
    result = {'baseline': str(baseline), 'candidate': str(candidate), 'common_rows': common_rows,
        'role': 'descriptive_common_window_comparison_does_not_change_registered_admission'}
    (output/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    lines = ['# 模型共同区间比较', '', '各自首次持仓指标另存own_holding_metrics.parquet；共同窗口保留首日收益和后续现金期。', '',
        '|模型|场景|成本|共同起点|年化|Sharpe|最大回撤|单边年换手|', '|---|---|---:|---|---:|---:|---:|---:|']
    for row in common_rows:
        lines.append(f"|{row['model']}|{row['variant']}|{row['cost_multiplier']:g}|{row['first']}|{row['cagr']:.2%}|{row['sharpe']:.2f}|{row['max_drawdown']:.2%}|{row['annualized_one_way_turnover']:.2f}|")
    lines += ['', '同期收益基准见common_benchmarks.parquet；本表作描述性归因，准入沿用各实验完整报告。']
    (output/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline', 'candidate', 'measurement-config', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    args = parser.parse_args()
    result = compare(**vars(args))
    print(json.dumps({'rows': len(result['common_rows']), 'output': str(args.output)}))


if __name__ == '__main__':
    main()
