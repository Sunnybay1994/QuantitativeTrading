"""Publish and read explicitly typed official price/total-return index levels."""

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

import polars as pl


def normalize_index(
    raw: pl.DataFrame, *, spec: dict[str, Any], sessions: list[dt.date], start: dt.date,
) -> pl.DataFrame:
    """Require every session including the prior-close anchor; never bridge a gap."""
    code = spec['index_code']
    if spec['return_type'] not in ('price', 'total_return'):
        raise ValueError('Explicit price or total_return classification required')
    if raw.is_empty() or set(raw['ts_code']) != {code}:
        raise ValueError(f'Empty or wrong index response: {code}')
    frame = raw.with_columns(pl.col('trade_date').str.to_date('%Y%m%d')).sort('trade_date')
    if frame['trade_date'].is_duplicated().any():
        raise ValueError(f'Duplicate index dates: {code}')
    if set(frame['trade_date']) != set(sessions):
        raise ValueError(f'Index dates do not match the complete calendar: {code}')
    if min(sessions) >= start:
        raise ValueError('A prior-session anchor is required')
    if frame.select('close', 'pre_close', 'pct_chg').null_count().sum_horizontal().item():
        raise ValueError(f'Missing index values: {code}')
    if frame.filter(
        ~pl.col('close').is_finite() | (pl.col('close') <= 0)
        | ~pl.col('pre_close').is_finite() | (pl.col('pre_close') <= 0)
        | ~pl.col('pct_chg').is_finite()
    ).height:
        raise ValueError(f'Invalid index values: {code}')
    # Both fields are published in points with four decimals. A mismatch is not silently rebased.
    if frame.filter((pl.col('pre_close') - pl.col('close').shift(1)).abs() > 0.00011).height:
        raise ValueError(f'Prior close discontinuity: {code}')
    if frame.filter(
        ((pl.col('close') / pl.col('pre_close') - 1) * 100 - pl.col('pct_chg')).abs() > 0.000051
    ).height:
        raise ValueError(f'Percent change unit or value mismatch: {code}')
    return frame.with_columns(
        (pl.col('close') / pl.col('close').shift(1) - 1).alias('daily_return'),
    ).filter(pl.col('trade_date') >= start).select(
        pl.lit(code).alias('index_code'), pl.lit(spec['name']).alias('index_name'),
        pl.lit(spec['return_type']).alias('return_type'), 'trade_date',
        pl.col('close').alias('index_level'), pl.col('pre_close').alias('previous_level'),
        'daily_return', pl.lit(spec['currency']).alias('currency'),
        pl.lit(spec['level_unit']).alias('level_unit'),
    )


def _directory(data_root: Path, version: str) -> Path:
    if not version or Path(version).name != version or version in ('.', '..'):
        raise ValueError('Invalid index version')
    return data_root / 'clean/index_benchmarks' / version


def publish(*, config: Path, captures: Path, data_root: Path) -> dict[str, Any]:
    settings = json.loads(config.read_text(encoding='utf-8'))
    records = json.loads(captures.read_text(encoding='utf-8'))
    output = _directory(data_root, settings['version'])
    if output.exists():
        raise FileExistsError('Choose a new clean index version')
    start, end = (dt.date.fromisoformat(settings[key]) for key in ('start', 'end'))
    calendar = pl.read_parquet(data_root / 'clean/trade_calendar/market=SH/data.parquet')
    opened = calendar.filter(pl.col('is_open')).sort('date')
    anchor = opened.filter(pl.col('date') < start)['date'].max()
    if anchor is None or end < start:
        raise ValueError('Invalid interval or missing prior session')
    sessions = opened.filter(pl.col('date').is_between(anchor, end))['date'].to_list()
    frames, details = [], []
    for spec in settings['series']:
        matches = [r for r in records if r['index_code'] == spec['index_code']]
        if len(matches) != 1 or not matches[0].get('rows'):
            raise ValueError(f"Missing unique capture: {spec['index_code']}")
        record = matches[0]
        if record['metadata']['ts_code'] != spec['index_code'] or record['return_type'] != spec['return_type']:
            raise ValueError('Metadata/capture classification mismatch')
        frame = normalize_index(pl.read_parquet(record['raw_path']), spec=spec, sessions=sessions, start=start)
        frames.append(frame)
        details.append({**spec, 'rows': frame.height, 'first': str(frame['trade_date'].min()),
                        'last': str(frame['trade_date'].max()), 'missing_dates': [], 'duplicates': 0,
                        'raw_path': record['raw_path'], 'metadata': record['metadata']})
    combined = pl.concat(frames)
    if combined.select('index_code', 'trade_date').is_duplicated().any():
        raise ValueError('Duplicate configured index series')
    result = {'version': settings['version'], 'start': str(start), 'end': str(end),
              'anchor': str(anchor), 'rows': combined.height, 'series': details,
              'units': 'index_level/previous_level: index points; daily_return: decimal fraction',
              'return_formula': 'close[t] / close[previous open session] - 1; prior-session anchor retained in raw',
              'availability': 'Index close is known after the session close; no execution or account constraints'}
    output.mkdir(parents=True)
    combined.write_parquet(output / 'data.parquet')
    (output / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def read_index_benchmark(
    *, data_root: Path, version: str, index_code: str, start: dt.date, end: dt.date,
    required_return_type: str = 'total_return',
) -> pl.DataFrame:
    """Return dated levels and decimal returns; price indexes require explicit opt-in."""
    if start > end or required_return_type not in ('price', 'total_return'):
        raise ValueError('Invalid index interval or return type')
    directory = _directory(data_root, version)
    summary = json.loads((directory / 'summary.json').read_text(encoding='utf-8'))
    specs = [s for s in summary['series'] if s['index_code'] == index_code]
    if len(specs) != 1 or specs[0]['return_type'] != required_return_type:
        raise ValueError('Index missing or return type differs; price is not total return')
    if str(start) < summary['start'] or str(end) > summary['end']:
        raise ValueError('Requested interval exceeds published coverage')
    return pl.scan_parquet(directory / 'data.parquet').filter(
        (pl.col('index_code') == index_code) & pl.col('trade_date').is_between(start, end)
    ).sort('trade_date').collect()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--captures', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    args = parser.parse_args()
    result = publish(config=args.config, captures=args.captures, data_root=args.data_root)
    print(f"Published {len(result['series'])} indexes, {result['rows']} rows: {result['version']}")


if __name__ == '__main__':
    main()
