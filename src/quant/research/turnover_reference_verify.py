"""Real-data shared-input verification without running a separate battery."""
import datetime as dt
import argparse
from pathlib import Path
import json

import polars as pl

from quant.data.factor_panels import available_sessions
from quant.data.refresh_stocks import read_stock_data
from quant.factors.compute import attach_expression_inputs
from quant.factors.turnover_reference import NAMES, CONTROLS
from quant.research.turnover_reference_family import digest, save


def verify(*, coverage: Path, output: Path, data_root: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    config = coverage/'refresh.toml'
    low, high, cutoff = dt.date(2024, 11, 1), dt.date(2025, 6, 30), dt.date(2025, 4, 30)
    code = [Path('src/quant/factors/compute.py'), Path('src/quant/research/factor_monthly.py'),
        Path('src/quant/data/factor_turnover_reference_inputs.py'), Path('src/quant/factors/turnover_reference.py'),
        Path('src/quant/data/refresh_stocks.py'), Path(__file__), config, coverage/'signals_2025.parquet']
    before = {str(p): digest(p) for p in code}
    save(output/'source_manifest_before.json', before)
    bars = read_stock_data(data_root=data_root, config=config, table='bar_1d', start=low, end=high,
        columns=('symbol', 'trade_date', 'close', 'adj_factor', 'volume'))
    calendar = available_sessions(data_root, high+dt.timedelta(days=40))
    def attach(frame, end):
        return attach_expression_inputs(frame, frame, expressions=NAMES, data_root=data_root,
            refresh_config=config, read_start=low, read_end=end, sessions=calendar)
    full = attach(bars, high)
    columns = ['symbol', 'trade_date', *NAMES, *CONTROLS]
    independent = pl.read_parquet(coverage/'signals_2025.parquet').filter(pl.col('trade_date') <= high).select(columns)
    keys = bars.select('symbol', 'trade_date')
    independent = independent.join(keys, on=['symbol', 'trade_date'], how='semi').sort('symbol', 'trade_date')
    actual = full.select(columns).join(independent.select('symbol', 'trade_date'),
        on=['symbol', 'trade_date'], how='semi').sort('symbol', 'trade_date')
    if not actual.equals(independent):
        raise ValueError('Shared production monthly values differ from full coverage computation')
    prefix = attach(bars.filter(pl.col('trade_date') <= cutoff), cutoff)
    if not prefix.equals(full.filter(pl.col('trade_date') <= cutoff)):
        raise ValueError('Production prefix differs')
    # Perturb future observations in memory; never change any stored input.
    from quant.data import factor_turnover_reference_inputs as source
    original = source.read_stock_data
    def disturbed(**kwargs):
        frame = original(**kwargs)
        fields = [c for c in ('close', 'adj_factor', 'volume', 'total_shares') if c in frame.columns]
        return frame.with_columns(*[pl.when(pl.col('trade_date') > cutoff).then(pl.col(c)*3.)
            .otherwise(pl.col(c)).alias(c) for c in fields])
    try:
        source.read_stock_data = disturbed
        altered = attach(bars, high)
    finally:
        source.read_stock_data = original
    if not altered.filter(pl.col('trade_date') <= cutoff).equals(prefix):
        raise ValueError('Future long-input changes altered an earlier signal or control')
    after = {p: digest(Path(p)) for p in before}
    frozen = json.loads((coverage/'source_manifest_before.json').read_text(encoding='utf-8'))
    # Existing full coverage already pinned the original source tables and calendars.
    if before != after or any(digest(Path(p)) != value for p, value in frozen.items()):
        raise ValueError('Frozen source bytes changed during integration verification')
    save(output/'source_manifest_after.json', after)
    actual.write_parquet(output/'production_monthly_values.parquet')
    result = {'production_vs_coverage_rows': actual.height, 'prefix_daily_rows': prefix.height,
        'candidate_columns': list(NAMES), 'matched_control_columns': list(CONTROLS),
        'month_end_values_equal': True, 'prefix_equal': True, 'future_input_perturbation_equal': True,
        'original_source_hashes_unchanged': len(frozen), 'label_data_read': False,
        'battery_runs': 0, 'account_runs': 0, 'auto_trade': False}
    save(output/'summary.json', result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--coverage', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    print(json.dumps(verify(**vars(parser.parse_args())), ensure_ascii=False))


if __name__ == '__main__':
    main()
