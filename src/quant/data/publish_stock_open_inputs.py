"""Publish a new opening-time execution snapshot from immutable local receipts."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tomllib

import polars as pl

from quant.data.refresh_stocks import read_stock_data, TABLES
from quant.data.stock_open_suspensions import POLICY, build_open_facts


def digest(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def write_json(path: Path, value: object) -> None:
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, default=str, allow_nan=False)


def publish(*, config: Path, output: Path) -> dict:
    spec = tomllib.loads(config.read_text(encoding='utf-8'))
    if spec['suspension_policy'] != POLICY or spec['auto_trade']:
        raise ValueError('Unsupported execution-input recipe')
    data = Path(spec['data_root'])
    old = data/'clean/stock_execution'/spec['source_snapshot']
    target = data/'clean/stock_execution'/spec['new_snapshot']
    if target.exists() or target.parent != old.parent or Path(spec['new_snapshot']).name != spec['new_snapshot']:
        raise ValueError('New snapshot must be a new sibling of the source snapshot')
    output.mkdir(parents=True, exist_ok=False)
    refresh = Path(spec['refresh_config'])
    recipe = tomllib.loads(refresh.read_text(encoding='utf-8'))
    inventory = Path(spec['receipt_inventory'])
    paths = [Path(v) for v in pl.read_parquet(inventory)['receipt']]
    legacy_raw = [Path(v) for v in json.loads((old/'sources.json').read_text(encoding='utf-8')) if 'suspend_d' in v]
    if not {p.resolve() for p in legacy_raw} <= {p.with_suffix('.parquet').resolve() for p in paths}:
        raise ValueError('Receipt inventory omits original suspension sources')
    keys = pl.read_parquet(old/'suspensions.parquet').select('symbol', 'trade_date').unique()
    low, high = keys['trade_date'].min(), keys['trade_date'].max()
    sources = [config, refresh, inventory, *old.glob('*.parquet'), old/'sources.json']
    sources += [Path(__file__), Path('src/quant/data/stock_open_suspensions.py'),
        Path('src/quant/data/stock_execution_inputs.py'), Path('src/quant/backtest/rules.py'),
        Path('src/quant/backtest/daily_simulator.py')]
    sources += [data/'clean/tushare_bulk/snapshots'/recipe['stock_snapshot']/'bar_1d/asset=stock'/f'year={year}'/'data.parquet'
        for year in range(low.year, high.year+1)]
    # The reader prefers complete increments over the declared historical snapshot.
    increments = [p for p in (data/'clean/tushare_incremental').glob('date=*')
        if str(low) <= p.name[5:] <= str(high) and all((p/f'{table}.parquet').exists() for table in TABLES)]
    sources += [p/f'{table}.parquet' for p in increments for table in TABLES]
    for metadata in paths:
        sources.extend([metadata, metadata.with_suffix('.parquet')])
    manifest = {str(p): digest(p) for p in sorted(set(sources))}
    write_json(output/'source_manifest_before.json', manifest)
    details, request_rows = [], []
    for metadata in paths:
        receipt = json.loads(metadata.read_text(encoding='utf-8'))
        raw = metadata.with_suffix('.parquet')
        if receipt['source'] != 'tushare' or receipt['table'] != 'suspend_d' or manifest[str(raw)] != receipt['checksum_sha256']:
            raise ValueError(f'Invalid suspension receipt: {metadata}')
        frame = pl.read_parquet(raw)
        if frame.height != receipt['rows']:
            raise ValueError('Suspension receipt row count differs')
        params = receipt['parameters']
        if raw in legacy_raw and (frame.height >= 5000 or not params.get('trade_date')
                or set(params) != {'trade_date'}):
            raise ValueError('Original suspension coverage is not an uncapped all-market date request')
        request_rows.append({'source_path': str(raw), 'source_metadata': str(metadata),
            'fetched_at': receipt['fetched_at'], 'parameters': json.dumps(params, sort_keys=True),
            'rows': frame.height, 'at_row_limit': frame.height >= 5000})
        if not frame.is_empty():
            normalized = frame.select(pl.col('ts_code').alias('symbol'), pl.col('trade_date').str.to_date('%Y%m%d'),
                'suspend_type', 'suspend_timing', pl.lit(str(raw)).alias('source_path'),
                pl.lit(str(metadata)).alias('source_metadata'), pl.lit(receipt['fetched_at']).alias('source_observed_at'))
            details.append(normalized.join(keys, on=['symbol', 'trade_date'], how='semi'))
    raw_details = pl.concat(details, how='vertical_relaxed')
    quote_frames = []
    for year in range(low.year, high.year+1):
        subset = keys.filter(pl.col('trade_date').dt.year() == year)
        if subset.is_empty():
            continue
        bars = read_stock_data(data_root=data, config=refresh, table='bar_1d',
            start=subset['trade_date'].min(), end=subset['trade_date'].max(), symbols=subset['symbol'].unique().to_list())
        quote_frames.append(bars.select('symbol', 'trade_date', 'volume').join(subset, on=['symbol', 'trade_date'], how='semi'))
    facts = build_open_facts(keys, raw_details, pl.concat(quote_frames))
    blocked = facts.filter(pl.col('open_status') != 'clear_at_open')
    after = {name: digest(Path(name)) for name in manifest}
    if after != manifest:
        raise ValueError('Inputs changed during opening-time snapshot construction')
    write_json(output/'source_manifest_after.json', after)
    target.mkdir(parents=True, exist_ok=False)
    # These independent execution inputs retain exactly their original bytes.
    for name in ('limits.parquet', 'dividends.parquet', 'instruments.parquet', 'sources.json'):
        shutil.copyfile(old/name, target/name)
    blocked.write_parquet(target/'suspensions.parquet')
    facts.write_parquet(target/'suspension_open_facts.parquet')
    raw_details.write_parquet(target/'suspension_source_details.parquet')
    pl.from_dicts(request_rows).write_parquet(target/'suspension_receipts.parquet')
    shutil.copyfile(config, target/'definition.toml')
    write_json(target/'source_manifest.json', manifest)
    result = {'source_snapshot': spec['source_snapshot'], 'snapshot': spec['new_snapshot'], 'suspension_policy': POLICY,
        'inherited_positive_keys': keys.height, 'status_counts': facts.group_by('open_status', 'open_reason').len().to_dicts(),
        'raw_receipts': len(paths), 'original_suspension_receipts': len(legacy_raw), 'source_hashes_unchanged': True,
        'original_inputs_unchanged': all(digest(p) == manifest[str(p)] for p in old.glob('*.parquet')),
        'unchanged_other_inputs': all(digest(target/name) == digest(old/name)
            for name in ('limits.parquet', 'dividends.parquet', 'instruments.parquet')),
        'coverage': 'Inherited positive suspension keys and original execution-date scope only; no new negative coverage or daily coverage claimed',
        'execution_model': 'Existing daily opening-price model; 09:30 boundary touching intervals block; not an intraday fill simulation',
        'unknown_policy': 'Conflicts remain OPEN_UNKNOWN, including positive daily volume with unspecified S timing',
        'vintage_limit': 'Raw receipts were collected retrospectively; corrected execution measurement is not contemporaneous source-vintage proof',
        'active_configuration_changed': False, 'api_calls': 0, 'account_runs': 0, 'battery_runs': 0, 'auto_trade': False}
    write_json(target/'summary.json', result)
    write_json(output/'summary.json', result)
    (output/'report.md').write_text('# 后续开盘执行输入版本\n\n```json\n'+json.dumps(result, ensure_ascii=False, indent=2)+'\n```\n', encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    print(json.dumps(publish(**vars(parser.parse_args())), ensure_ascii=False))


if __name__ == '__main__':
    main()
