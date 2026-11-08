"""Bounded CFFEX daily permission check; inputs for monthly reporting only."""
import datetime as dt
import json
from pathlib import Path
import tomllib

import polars as pl

from quant.data.connectors.tushare import TushareConnector
from quant.data.storage import RawStore, publish_directory
from quant.data.structured_availability import release_at, sessions
from quant.data.structured_native_rows import native_row_id
from quant.data.realtime_store import atomic_json


def capture(*, as_of, output, data_root=Path('data'), config=Path('configs/data/structured_sources.toml'),
            connector=None, probe_receipt=None):
    from quant.data.structured_incremental import _yield_check
    _yield_check(data_root)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    rule = tomllib.loads(Path(config).read_text(encoding='utf-8'))['futures']
    calendar = sessions(data_root)
    day = max(d for d in calendar if d <= as_of)
    if probe_receipt:
        import hashlib
        item = json.loads(Path(probe_receipt).read_text(encoding='utf-8'))['fut_daily']
        path = Path(item['raw_path'])
        metadata = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
        if hashlib.sha256(path.read_bytes()).hexdigest() != metadata['checksum_sha256']:
            raise ValueError('Permission probe raw checksum differs')
        frame = pl.read_parquet(path)
        observed = dt.datetime.fromisoformat(metadata['fetched_at'])
    else:
        frame = (connector or TushareConnector()).query_raw('fut_daily',
            trade_date=day.strftime('%Y%m%d'), exchange=rule['exchange'], limit='2000', offset='0')
        observed = dt.datetime.now(dt.timezone.utc)
        raw = RawStore(Path(data_root)/'raw').write(source='tushare', table='fut_daily', frame=frame,
            parameters={'trade_date': day.strftime('%Y%m%d'), 'exchange': rule['exchange'],
                        'consumer': 'D2_monthly_market_only'}, fetched_at=observed)
        path = raw.data_path
    if frame.is_empty() or frame.height >= 2000:
        raise ValueError('Empty or potentially truncated futures response')
    if set(frame['trade_date']) != {day.strftime('%Y%m%d')}:
        raise ValueError('Futures date scope mismatch')
    selected = frame.filter(pl.col('ts_code').str.contains(r'^(IF|IC|IM)[0-9]{4}\.CFX$'))
    products = selected['ts_code'].str.slice(0, 2).unique().to_list()
    if set(products) != set(rule['products']) or selected['ts_code'].is_duplicated().any():
        raise ValueError('Require unique daily contracts for IF/IC/IM')
    for col in ('close', 'settle'):
        if selected.filter(pl.col(col).is_null() | ~pl.col(col).is_finite() | (pl.col(col) <= 0)).height:
            raise ValueError('Invalid futures quote')
    available = max(observed, release_at(day, rule, calendar).astimezone(dt.timezone.utc))
    selected = selected.with_columns(pl.Series('source_row_id',
        [native_row_id(r) for r in selected.iter_rows(named=True)]),
        pl.lit(observed).alias('observed_at'), pl.lit(available).alias('available_at'),
        pl.lit(str(path)).alias('source_raw_path'), pl.lit(rule['units']).alias('native_units'))
    staging = output/'clean'
    staging.mkdir()
    selected.write_parquet(staging/'data.parquet')
    result = {'status': 'captured', 'trade_date': str(day), 'rows': selected.height,
        'products': sorted(products), 'raw_path': str(path), 'observed_at': observed.isoformat(),
        'consumer': 'monthly_market_panel_only', 'basis_status': 'unknown_no_matching_spot_series',
        'auto_trade': False}
    atomic_json(staging/'summary.json', result)
    destination = Path(data_root)/'clean/fut_daily'/f'snapshot=d2_{output.name}'
    destination.parent.mkdir(parents=True, exist_ok=True)
    publish_directory(staging, destination, staging_root=output, destination_root=destination.parent)
    result['clean_path'] = str(destination)
    atomic_json(output/'summary.json', result)
    return result
