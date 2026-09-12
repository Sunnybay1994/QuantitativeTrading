"""Report registered historical shocks without changing existing admissions."""
import argparse
import datetime as dt
import json
from pathlib import Path
import tomllib

import polars as pl

from quant.data.equal_weight_index import load_return_benchmarks
from quant.reporting.cycle_stress import path_statistics
from quant.research.factor_battery_cost_report import load_cost_history


def evaluate(nav: pl.DataFrame, benchmark: pl.DataFrame, windows: list[dict]) -> list[dict]:
    if (not nav['date'].equals(benchmark['date']) or nav.is_empty()
            or not nav['date'].is_sorted() or nav['date'].n_unique() != nav.height
            or nav['market_value'].null_count() or not nav['market_value'].is_finite().all()
            or (nav['market_value'] < 0).any()
            or {'equity', 'cash', 'market_value'} & set(benchmark.columns)):
        raise ValueError('Require aligned complete NAV and return index')
    if not windows or len({w['name'] for w in windows}) != len(windows):
        raise ValueError('Require distinct windows')
    exposed = nav.with_columns(((pl.col('market_value') > 0) |
        (pl.col('market_value').shift(1).fill_null(0) > 0)).alias('exposed'))
    first = nav.filter(pl.col('market_value') > 0)['date'].min()
    rows = []
    for window in windows:
        low, high = window['start'], window['end']
        if low > high:
            raise ValueError('Invalid window')
        part = exposed.filter(pl.col('date').is_between(low, high))
        # Calendar endpoints may be weekends. Require NAV on both sides instead
        # of treating the first/last exchange session as a missing calendar day.
        full = nav['date'][0] <= low and nav['date'][-1] >= high
        applicable = bool(full and part.height and first is not None and
                          part['date'][0] >= first and part['exposed'].any())
        row = {'window': window['name'], 'start': low, 'end': high,
               'applicable': applicable, 'not_worse': None,
               'reason': None if applicable else ('incomplete_history' if not full else
                   'before_holding_window' if first is None or not part.height or part['date'][0] < first
                   else 'cash_only_window')}
        if applicable:
            strategy = path_statistics(nav, start=low, end=high)
            reference = path_statistics(benchmark, start=low, end=high)
            row.update(strategy_return=strategy['total_return'],
                benchmark_return=reference['total_return'],
                strategy_drawdown=strategy['max_drawdown'],
                benchmark_drawdown=reference['max_drawdown'],
                exposed_sessions=part['exposed'].sum(), sessions=part.height,
                not_worse=strategy['total_return'] >= reference['total_return'] and
                    abs(strategy['max_drawdown']) <= abs(reference['max_drawdown']))
        rows.append(row)
    return rows


def run(*, config: Path, output: Path, data_root: Path = Path('data')) -> dict:
    spec = tomllib.loads(config.read_text(encoding='utf-8'))
    if spec['scope'] != 'retrospective_diagnostic_only' or spec['auto_trade'] is not False:
        raise ValueError('Diagnostic configuration required')
    benchmarks = load_return_benchmarks(config=Path(spec['benchmark_config']),
        data_root=data_root, start=spec['start'], end=spec['end'])
    rows: list[dict] = []
    summaries: list[dict] = []
    for candidate in spec['candidates']:
        histories = {cost: load_cost_history(Path(candidate['run']), candidate['variant'], cost,
                                             spec['end'])[0] for cost in (.5, 1., 2.)}
        first = histories[1.].filter(pl.col('market_value') > 0)['date'].min()
        if first is None:
            raise ValueError('Candidate has no original holding window for benchmark selection')
        if not isinstance(first, dt.date):
            raise ValueError('NAV must use calendar dates')
        strongest = sorted(benchmarks, key=lambda name: (
            -path_statistics(benchmarks[name], start=first, end=spec['end'])['cagr'], name))[0]
        for cost, nav in histories.items():
            shocks = evaluate(nav, benchmarks[strongest], spec['windows'])
            rows.extend({'candidate': candidate['name'], 'cost': cost, 'benchmark': strongest,
                         **row} for row in shocks)
            summaries.append({'candidate': candidate['name'], 'cost': cost, 'benchmark': strongest,
                'total': len(shocks), 'applicable': sum(r['applicable'] for r in shocks),
                'not_worse': sum(r['not_worse'] is True for r in shocks)})
    result = {'scope': spec['scope'], 'original_decisions_changed': False,
              'overlap': spec['overlap'], 'summary': summaries, 'windows': rows}
    output.mkdir(parents=True, exist_ok=False)
    (output/'config.toml').write_bytes(config.read_bytes())
    pl.from_dicts(rows, infer_schema_length=None).write_csv(output/'windows.csv')
    (output/'summary.json').write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    print(json.dumps(run(**vars(parser.parse_args()))['summary']))
