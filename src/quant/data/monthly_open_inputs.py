"""Local receipt normalization and immutable monthly opening-policy publications."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import polars as pl

from quant.data.stock_open_suspensions import POLICY, build_open_facts


def digest(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def policy_of(folder: Path) -> str:
    schema = pl.read_parquet_schema(folder/'suspensions.parquet')
    if 'suspension_policy' not in schema:
        return 'legacy_daily_binary'
    frame = pl.read_parquet(folder/'suspensions.parquet')
    if frame.filter((pl.col('suspension_policy') != POLICY).fill_null(True)
            | ~pl.col('open_status').is_in(['unknown', 'halt_at_open']).fill_null(False)).height:
        raise ValueError('Mixed or invalid monthly suspension policy')
    return POLICY


def daily_open_facts(folder: Path, day: dt.date, bars: pl.DataFrame) -> tuple[pl.DataFrame, dict]:
    """Use original positive keys and raw intervals; absent details stay unknown."""
    provenance = json.loads((folder/'sources.json').read_text(encoding='utf-8'))
    if provenance['as_of'] != str(day):
        raise ValueError('Wrong-date daily suspension provenance')
    keys = pl.read_parquet(folder/'suspensions.parquet').select('symbol', 'trade_date').unique()
    if keys.filter(pl.col('trade_date') != day).height:
        raise ValueError('Wrong-date daily suspension keys')
    schema = {'symbol': pl.String, 'trade_date': pl.Date, 'suspend_type': pl.String,
              'suspend_timing': pl.String, 'source_path': pl.String}
    details, manifest, verified_negative = [], {}, False
    for name in provenance['raw']:
        raw = Path(name)
        if raw.parent.parent.name != 'suspend_d':
            continue
        meta_path = raw.with_suffix('.json')
        if not raw.is_file() or not meta_path.is_file():
            continue
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
        frame = pl.read_parquet(raw)
        manifest.update({str(raw): digest(raw), str(meta_path): digest(meta_path)})
        if (meta['source'] != 'tushare' or meta['table'] != 'suspend_d'
                or meta['checksum_sha256'] != manifest[str(raw)] or frame.height != meta['rows']):
            raise ValueError('Invalid daily suspension raw receipt')
        if meta['parameters'] != {'trade_date': day.strftime('%Y%m%d')} or frame.height >= 5000:
            raise ValueError('Daily suspension request is not complete all-market coverage')
        verified_negative = True
        if frame.is_empty():
            continue
        if set(frame['trade_date']) != {day.strftime('%Y%m%d')}:
            raise ValueError('Wrong-date raw suspension records')
        if not {'suspend_type', 'suspend_timing'} <= set(frame.columns):
            verified_negative = False
            continue
        values = frame.select(pl.col('ts_code').alias('symbol'),
            pl.col('trade_date').str.to_date('%Y%m%d'), 'suspend_type', 'suspend_timing',
            pl.lit(str(raw)).alias('source_path'))
        keys = pl.concat([keys, values.filter(pl.col('suspend_type') == 'S').select(keys.columns)]).unique()
        details.append(values)
    # Without a complete date request, absence of a positive row proves nothing.
    if not verified_negative:
        universe = pl.read_parquet(folder/'instruments.parquet').select('symbol').with_columns(
            pl.lit(day).alias('trade_date'))
        keys = pl.concat([keys, universe]).unique()
    keys = keys.filter(pl.col('symbol').str.contains(r'^[0-9]{6}\.(SH|SZ)$'))
    detail = pl.concat(details, how='vertical_relaxed') if details else pl.DataFrame(schema=schema)
    facts = build_open_facts(keys, detail, bars)
    return facts, {'date': str(day), 'negative_coverage_verified': verified_negative, 'raw_hashes': manifest}


def extension_identity(settings: dict, as_of: dt.date) -> dict:
    root = Path(settings.get('data_root', 'data'))
    folder = root/'clean/stock_execution'/settings['execution_snapshot']
    paths = [*folder.glob('*.parquet'), *folder.glob('*.json')]
    paths += [Path(settings['battery_config'])]
    return {'as_of': str(as_of), 'source_snapshot': settings['execution_snapshot'],
            'policy': policy_of(folder), 'sources': {str(p): digest(p) for p in sorted(paths)}}


def extension_version(settings: dict, as_of: dt.date) -> str:
    folder = Path(settings.get('data_root', 'data'))/'clean/stock_execution'/settings['execution_snapshot']
    if not folder.exists():  # synthetic callers still receive source-separated names
        identity = {'execution_snapshot': settings['execution_snapshot'], 'battery_config': settings['battery_config']}
    else:
        identity = extension_identity(settings, as_of)
    token = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
    return f'nightly_month_{as_of:%Y%m%d}_{token}'


def evaluation_source_identity(settings: dict) -> bytes:
    """Keep legacy batch IDs; opening-policy batteries cannot reuse their cache."""
    folder = Path(settings['data_root'])/'clean/stock_execution'/settings['execution_snapshot']
    if policy_of(folder) != POLICY:
        return b''
    identity = extension_identity(settings, settings['as_of'])
    identity['return_benchmark_sha256'] = digest(Path(settings['return_benchmark_config']))
    return json.dumps(identity, sort_keys=True).encode()


def validate_binding(settings: dict, data_root: Path) -> None:
    """Opening-policy inputs require an explicit compatible return-index identity."""
    import tomllib
    folder = data_root/'clean/stock_execution'/settings['execution_snapshot']
    if policy_of(folder) != POLICY:
        return
    config = tomllib.loads(Path(settings['return_benchmark_config']).read_text(encoding='utf-8'))
    index = data_root/'clean/equal_weight_indexes'/config['benchmarks']['equal_weight_snapshot']
    summary = json.loads((index/'summary.json').read_text(encoding='utf-8'))
    if summary['execution_snapshot'] == settings['execution_snapshot']:
        return
    binding = config.get('execution_binding', {})
    if binding.get('execution_snapshot') != settings['execution_snapshot']:
        raise ValueError('Return benchmark is not bound to opening-policy execution inputs')
    proof = json.loads(Path(binding['proof']).read_text(encoding='utf-8'))
    if (digest(Path(binding['proof'])) != binding['proof_sha256'] or not proof['return_series_unchanged']
            or proof['execution_snapshot'] != settings['execution_snapshot']
            or proof['equal_weight_snapshot'] != index.name
            or proof['source_execution_snapshot'] != summary['execution_snapshot']):
        raise ValueError('Invalid execution/return benchmark compatibility proof')
    for name, expected in proof['hashes'].items():
        if digest(Path(name)) != expected:
            raise ValueError('Execution/return benchmark binding source changed')
