"""Original-eligible coverage for the fixed turnover-reference family; no return labels."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil
import time
import tomllib

import polars as pl

from quant.data.factor_panels import available_sessions
from quant.data.factor_turnover_reference_inputs import read_turnover_reference, turnover_reference_start
from quant.data.refresh_stocks import TABLES
from quant.factors.turnover_reference import NAMES, CONTROLS


def digest(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def save(path: Path, value: object) -> None:
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, default=str, allow_nan=False)


def run(*, output: Path, refresh: Path, definition: Path, universe: Path, data_root: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    spec = tomllib.loads(definition.read_text(encoding='utf-8'))
    if tuple(spec['signals']) != NAMES or tuple(spec['matched_controls']) != CONTROLS or spec['directions'] != [1, 1]:
        raise ValueError('Only the fixed turnover-reference family is implemented')
    shutil.copyfile(refresh, output/'refresh.toml')
    shutil.copyfile(definition, output/'definition.toml')
    config = output/'refresh.toml'
    settings = tomllib.loads(config.read_text(encoding='utf-8'))
    start, end = dt.date(2010, 1, 1), dt.date(2025, 12, 31)
    calendar = available_sessions(data_root, end+dt.timedelta(days=40))
    signals = tuple(a for a, b in zip(calendar, calendar[1:])
        if (a.year, a.month) != (b.year, b.month) and start <= a <= end)
    low = turnover_reference_start(signals[0])
    sources = [refresh, definition, config, output/'definition.toml', Path(__file__),
        Path('src/quant/factors/turnover_reference.py'), Path('src/quant/data/factor_turnover_reference_inputs.py'),
        Path('src/quant/data/refresh_stocks.py'), Path('src/quant/data/factor_panels.py')]
    for root in (data_root/'clean/tushare_bulk/snapshots'/settings['stock_snapshot']/'bar_1d/asset=stock',
                 data_root/'clean/tushare_daily_basic/snapshots'/settings['daily_basic_snapshot']):
        sources += [p for year in range(low.year, end.year+1) for p in (root/f'year={year}').glob('*.parquet')]
    sources += [p/f'{table}.parquet' for p in (data_root/'clean/tushare_incremental').glob('date=*')
        if str(low) <= p.name[5:] <= str(end) and all((p/f'{t}.parquet').exists() for t in TABLES) for table in TABLES]
    sources += [data_root/f'clean/trade_calendar/market={market}/data.parquet' for market in ('SH', 'SZ')]
    sources += [universe/str(year)/'universe.parquet' for year in range(2010, 2026)]
    before = {str(p): digest(p) for p in sorted(set(sources))}
    save(output/'source_manifest_before.json', before)
    counts, annual = [], []
    for year in range(2010, 2026):
        clock = time.perf_counter()
        first, last = dt.date(year, 1, 1), dt.date(year, 12, 31)
        values = read_turnover_reference(data_root=data_root, refresh_config=config, calendar=calendar,
            start=first, end=last)
        values.write_parquet(output/f'signals_{year}.parquet')
        if values.select('symbol', 'trade_date').is_duplicated().any():
            raise ValueError('Signal identities duplicated')
        valid = values.filter(pl.col('status') == 'valid')
        if valid.filter(~pl.all_horizontal(pl.col(c).is_finite() for c in (*NAMES, *CONTROLS))).height:
            raise ValueError('Matched controls do not share the valid signal cohort')
        keys = pl.read_parquet(universe/str(year)/'universe.parquet', columns=['symbol', 'trade_date', 'eligible'])
        keys = keys.filter(pl.col('eligible') & pl.col('trade_date').is_in(signals)).select('symbol', 'trade_date')
        eligible = keys.join(values, on=['symbol', 'trade_date'], how='left', validate='1:1')
        per_month = eligible.group_by('trade_date').agg(pl.len().alias('eligible_count'),
            *[pl.col(name).count().alias(name+'_count') for name in (*NAMES, *CONTROLS)]).sort('trade_date')
        counts.append(per_month)
        eligible.group_by('trade_date', 'status').len().sort('trade_date', 'status').write_parquet(output/f'eligible_status_{year}.parquet')
        result = {'year': year, 'all_symbol_months': values.height, 'valid_all_symbol_months': valid.height,
            'eligible_symbol_months': eligible.height, 'valid_eligible_symbol_months': eligible[NAMES[0]].count(),
            'months_at_least_100': per_month.filter(pl.col(NAMES[0]+'_count') >= 100).height,
            'seconds': time.perf_counter()-clock}
        annual.append(result)
        print(json.dumps(result), flush=True)
    monthly = pl.concat(counts).with_columns(*[(pl.col(name+'_count')/pl.col('eligible_count')).alias(name+'_coverage') for name in NAMES])
    monthly.write_parquet(output/'monthly_coverage.parquet')
    after = {name: digest(Path(name)) for name in before}
    save(output/'source_manifest_after.json', after)
    if before != after:
        raise ValueError('Frozen input or kernel changed during full-market coverage computation')
    enough = all(monthly.filter(pl.col(n+'_count') >= 100).height >= 96 for n in NAMES)
    result = {'family': spec['family'], 'first_signal': str(signals[0]), 'last_signal': str(signals[-1]),
        'eligible_stock_months': monthly['eligible_count'].sum(), 'annual': annual,
        'signals': {name: {'valid_eligible_stock_months': monthly[name+'_count'].sum(),
            'months_at_least_100': monthly.filter(pl.col(name+'_count') >= 100).height,
            'first_month_at_least_100': monthly.filter(pl.col(name+'_count') >= 100)['trade_date'].min(),
            'median_eligible_coverage': monthly[name+'_coverage'].median()} for name in NAMES},
        'matched_controls_same_valid_cohort': True, 'source_hashes_unchanged': len(before),
        'computable_coverage_supports_original_admission_attempt': enough,
        'next': 'Integrate fixed whole family into original N1/N3/N4' if enough else 'Unknown due to insufficient complete signal coverage; stop this fixed family without window changes',
        'formal_ic_months': 'Not measured; coverage counts are not formal statistical or incremental admission months',
        'scope': spec['scope'], 'vintage_limitation': spec['snapshot_boundary'],
        'label_data_read': False, 'account_runs': 0, 'battery_runs': 0, 'auto_trade': False}
    save(output/'summary.json', result)
    (output/'report.md').write_text('# 换手参考价整族的原可投池信号覆盖\n\n```json\n'+json.dumps(result, ensure_ascii=False,
        indent=2, default=str)+'\n```\n', encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--refresh', type=Path, default=Path('configs/data/refresh_q2_sue_v2_model_20260912.toml'))
    parser.add_argument('--definition', type=Path, default=Path('configs/research/turnover_reference_price_family_v1.toml'))
    parser.add_argument('--universe', type=Path, default=Path('artifacts/factors/battery_statistics_20260831_20260911/inputs'))
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    print(json.dumps(run(**vars(parser.parse_args())), ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()
