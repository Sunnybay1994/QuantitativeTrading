"""Bounded Hong Kong daily-price and southbound history permission/quality probe."""
import argparse
import datetime as dt
import json
import time
import tomllib
from pathlib import Path

import polars as pl

from quant.data.connectors.tushare import TushareConnector
from quant.data.tushare_bulk import _classify_probe_exception


def profile(frame: pl.DataFrame) -> dict:
    result: dict = {'rows': frame.height, 'columns': frame.columns,
                    'null_counts': frame.null_count().row(0, named=True) if frame.width else {}}
    if frame.is_empty():
        return result
    date_column = next((key for key in ('trade_date', 'as_of', 'date') if key in frame.columns), None)
    if date_column:
        result.update(first=str(frame[date_column].min()), last=str(frame[date_column].max()),
                      dates=frame[date_column].n_unique())
        keys = [key for key in (date_column, 'ts_code', 'symbol', 'exchange') if key in frame.columns]
        result['duplicate_keys'] = frame.select(keys).is_duplicated().sum()
    for key in ('vol', 'amount', 'ratio', 'adj_factor'):
        if key in frame.columns:
            values = frame[key].cast(pl.Float64, strict=False)
            result[key] = {'minimum': values.min(), 'maximum': values.max(),
                           'nonfinite': (~values.is_finite()).sum()}
    return result


def probe(*, config: Path, output: Path, data_root: Path) -> dict:
    settings = tomllib.loads(config.read_text(encoding='utf-8'))
    spec = settings['probe']
    output.mkdir(parents=True, exist_ok=False)
    (output/'config.toml').write_bytes(config.read_bytes())
    raw = data_root/'raw'/'hk_low_frequency_probe'/output.name
    raw.mkdir(parents=True, exist_ok=False)
    requests = []
    for api in spec.get('price_apis', ('hk_daily', 'hk_adjfactor', 'hk_daily_adj')):
        for symbol in spec['symbols']:
            requests.append((api, {'ts_code': symbol, 'start_date': spec['price_start'], 'end_date': spec['end']}))
    split = dt.datetime.strptime(spec['hold_split'], '%Y%m%d').date()
    for symbol in spec.get('hold_symbols', spec['symbols']):
        for low, high in ((spec['hold_start'], (split-dt.timedelta(days=1)).strftime('%Y%m%d')),
                          (spec['hold_split'], spec['end'])):
            requests.append(('hk_hold', {'ts_code': symbol, 'exchange': 'HK', 'start_date': low, 'end_date': high}))
    for year in spec['flow_years']:
        requests.append(('moneyflow_hsgt', {'start_date': f'{year}0101',
                         'end_date': min(f'{year}1231', spec['end'])}))
    if len(requests) > spec['maximum_requests']:
        raise ValueError('Probe exceeds frozen request allowance')
    client = TushareConnector()
    rows, denied = [], set()
    for number, (api, params) in enumerate(requests, 1):
        if api in denied:
            rows.append({'api': api, 'params': params, 'result': 'skipped_after_permission_denial'})
            continue
        stamp = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            frame = client.query_raw(api, **params)
            frame.write_parquet(raw/f'{number:02d}_{api}.parquet')
            row = {'api': api, 'params': params, 'result': 'returned', 'captured_at': stamp,
                   'raw_file': str(raw/f'{number:02d}_{api}.parquet'), **profile(frame)}
        except Exception as exc:
            reason = _classify_probe_exception(exc)
            row = {'api': api, 'params': params, 'result': reason.lower(), 'captured_at': stamp}
            if reason == 'PERMISSION_DENIED':
                denied.add(api)
        rows.append(row)
        (output/'requests.json').write_text(json.dumps(rows, indent=2, default=str), encoding='utf-8')
        print(json.dumps({key: row[key] for key in ('api', 'params', 'result')} |
                         {'rows': row.get('rows')}, ensure_ascii=True), flush=True)
        time.sleep(spec['interval_seconds'])
    local = {}
    watch = tomllib.loads(Path(settings['local']['watch_pool']).read_text(encoding='utf-8'))
    symbols = [row['symbol'] for row in watch['members']]
    paths = sorted((data_root/'clean'/'bar_1d').glob('date=*/data.parquet'))
    bars = pl.scan_parquet(paths).filter(pl.col('symbol').is_in(symbols)).collect()
    local['watch_daily'] = profile(bars)
    bars.group_by('symbol').agg(pl.len().alias('rows'), pl.col('trade_date').min().alias('first'),
        pl.col('trade_date').max().alias('last')).sort('symbol').write_parquet(output/'local_daily_coverage.parquet')
    for version in settings['local']['eligibility']:
        folder = data_root/'clean'/'hk_connect_eligibility'/version
        local[version] = json.loads((folder/'coverage.json').read_text())
        events = pl.read_parquet(folder/'events.parquet')
        local[version]['missing_publication_dates'] = events['published_date'].null_count()
    result = {'requests': rows, 'local': local}
    (output/'summary.json').write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    args = parser.parse_args()
    probe(config=args.config, output=args.output, data_root=args.data_root)


if __name__ == '__main__':
    main()
