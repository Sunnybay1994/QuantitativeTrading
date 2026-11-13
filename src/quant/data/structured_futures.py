"""Bounded CFFEX daily permission check; inputs for monthly reporting only."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import tomllib
import uuid

import polars as pl

from quant.data.connectors.tushare import TushareConnector
from quant.data.storage import RawStore, publish_directory
from quant.data.structured_availability import release_at, sessions
from quant.data.structured_native_rows import native_row_id
from quant.data.realtime_store import atomic_json


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _capture(*, as_of, output, data_root, config, connector, probe_receipt, attempt):
    rule = tomllib.loads(Path(config).read_text(encoding='utf-8'))['futures']
    calendar = sessions(data_root)
    day = max(d for d in calendar if d <= as_of)
    saved = output/'summary.json'
    prior = json.loads(saved.read_text(encoding='utf-8')) if saved.exists() else None
    failed = output/'clean/summary.json'  # Old failed publications retained their raw here.
    cached = prior or (json.loads(failed.read_text(encoding='utf-8')) if failed.exists() else None)
    if cached is None:
        failures = [json.loads(p.read_text(encoding='utf-8')) for p in (output/'attempts').glob('*.json')]
        failures = [r for r in failures if r.get('status') == 'failed' and r.get('raw_path')
                    and r.get('as_of') == str(as_of)]
        if failures:
            cached = {**max(failures, key=lambda r: r['finished_at']), 'trade_date': str(day)}
    if cached and cached['trade_date'] != str(day):
        raise ValueError('Output belongs to another source date; use a new output')
    if probe_receipt:
        item = json.loads(Path(probe_receipt).read_text(encoding='utf-8'))['fut_daily']
        path = Path(item['raw_path'])
    elif cached:
        path = Path(cached['raw_path'])
    else:
        params = {'trade_date': day.strftime('%Y%m%d'), 'exchange': rule['exchange'],
                  'limit': '2000', 'offset': '0'}
        frame = (connector or TushareConnector()).query_raw('fut_daily', **params)
        observed = dt.datetime.now(dt.timezone.utc)
        raw = RawStore(Path(data_root)/'raw').write(source='tushare', table='fut_daily', frame=frame,
            parameters={**params, 'consumer': 'D2_monthly_market_only'}, fetched_at=observed)
        path = raw.data_path
    metadata = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    if (checksum != metadata['checksum_sha256'] or metadata['source'] != 'tushare'
            or metadata['table'] != 'fut_daily'):
        raise ValueError('Futures raw checksum or provider identity differs')
    provider_params = {k: v for k, v in metadata['parameters'].items() if k != 'consumer'}
    if (provider_params.get('trade_date') != day.strftime('%Y%m%d')
            or provider_params.get('exchange') != rule['exchange']):
        raise ValueError('Futures raw provider parameters differ from requested date/exchange')
    observed = dt.datetime.fromisoformat(metadata['fetched_at']).astimezone(dt.timezone.utc)
    frame = pl.read_parquet(path)
    attempt.update(raw_path=str(path), raw_sha256=checksum, observed_at=observed.isoformat())
    limit = min(2000, int(provider_params.get('limit', '2000')))
    if frame.is_empty() or frame.height >= limit:
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
    rule_hash = _digest(rule)
    identity = {'schema_version': 1, 'raw_sha256': checksum, 'observed_at': observed.isoformat(),
                'provider_parameters': provider_params, 'futures_rule_sha256': rule_hash}
    version = _digest(identity)
    destination = Path(data_root)/'clean/fut_daily'/f'snapshot=d2_futures_{day:%Y%m%d}_{version}'
    if prior and prior.get('version_sha256') != version:
        raise FileExistsError('Published output has another or legacy version; use a new output')
    result = {'status': 'captured', 'trade_date': str(day), 'rows': selected.height,
        'products': sorted(products), 'raw_path': str(path), 'observed_at': observed.isoformat(),
        **identity, 'version_sha256': version, 'available_at': available.isoformat(),
        'provider_parameters_complete': {'trade_date', 'exchange', 'limit', 'offset'} <= set(provider_params),
        'clean_path': str(destination),
        'consumer': 'monthly_market_panel_only', 'basis_status': 'unknown_no_matching_spot_series',
        'auto_trade': False}

    def reuse():
        record = json.loads((destination/'summary.json').read_text(encoding='utf-8'))
        if (record.get('version_sha256') != version or record.get('raw_sha256') != checksum
                or hashlib.sha256((destination/'data.parquet').read_bytes()).hexdigest() != record.get('clean_sha256')
                or not pl.read_parquet(destination/'data.parquet').equals(selected)):
            raise ValueError('Existing immutable futures publication differs from its version')
        return {**record, 'reused': True}

    if destination.exists():
        result = reuse()
    else:
        staging = output/('clean_'+uuid.uuid4().hex)
        staging.mkdir()
        selected.write_parquet(staging/'data.parquet')
        result['clean_sha256'] = hashlib.sha256((staging/'data.parquet').read_bytes()).hexdigest()
        atomic_json(staging/'summary.json', result)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            publish_directory(staging, destination, staging_root=output, destination_root=destination.parent)
        except FileExistsError:
            result = reuse()  # A concurrent identical version is reuse, never replacement.
    if not saved.exists():
        atomic_json(saved, result)
    return result


def capture(*, as_of, output, data_root=Path('data'), config=Path('configs/data/structured_sources.toml'),
            connector=None, probe_receipt=None):
    from quant.data.structured_incremental import _yield_check
    from quant.data.realtime import single_writer
    _yield_check(data_root)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with single_writer(output/'writer.lock'):
        attempt_path = output/'attempts'/(uuid.uuid4().hex+'.json')
        attempt = {'status': 'running', 'started_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                   'as_of': str(as_of), 'auto_trade': False}
        atomic_json(attempt_path, attempt)
        try:
            result = _capture(as_of=as_of, output=output, data_root=data_root, config=config,
                              connector=connector, probe_receipt=probe_receipt, attempt=attempt)
            attempt.update(status='captured', version_sha256=result['version_sha256'], reused=result.get('reused', False))
            return result
        except Exception as exc:
            attempt.update(status='failed', error_type=type(exc).__name__, error=str(exc))
            raise
        finally:
            attempt['finished_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
            atomic_json(attempt_path, attempt)
