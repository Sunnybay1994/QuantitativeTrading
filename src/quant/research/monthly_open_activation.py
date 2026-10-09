"""Publish and verify a local monthly opening-policy sibling, without account replay."""
import argparse
import datetime as dt
import json
from pathlib import Path
import shutil
import tomllib

import polars as pl

from quant.data.monthly_open_inputs import daily_open_facts, digest, policy_of, validate_binding
from quant.data.nightly_month_inputs import _write_toml, _execution_end, _mutable_capture_floor, inspect_month_inputs
from quant.data.refresh_stocks import read_stock_data
from quant.data.stock_open_suspensions import POLICY


def save(path, value):
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, default=str)


def publish(config: Path, output: Path) -> dict:
    spec = tomllib.loads(config.read_text(encoding='utf-8'))
    if spec['auto_trade'] or spec['suspension_policy'] != POLICY:
        raise ValueError('Invalid opening-policy recipe')
    root = Path(spec['data_root'])
    old = root/'clean/stock_execution'/spec['source_month']
    corrected = root/'clean/stock_execution'/spec['source_open']
    target = root/'clean/stock_execution'/spec['version']
    if target.exists() or Path(spec['version']).name != spec['version']:
        raise ValueError('New monthly version must be unused')
    output.mkdir(parents=True, exist_ok=False)
    base_settings = json.loads(Path(spec['prepared_settings']).read_text(encoding='utf-8'))
    settings = {**tomllib.loads(Path(spec['nightly_config']).read_text(encoding='utf-8')), **base_settings}
    if settings['execution_snapshot'] != old.name:
        raise ValueError('Prepared settings do not identify source month')
    as_of = spec['as_of']
    if _execution_end(settings, root) != as_of or _mutable_capture_floor(old) < as_of:
        raise ValueError('Source monthly corporate-action coverage is insufficient')
    provenance = json.loads((old/'sources.json').read_text(encoding='utf-8'))
    daily = [Path(p) for p in provenance['daily']]
    immutable = [config, Path(spec['prepared_settings']), *old.glob('*'), *corrected.glob('*')]
    for folder in daily:
        immutable.extend(folder.glob('*'))
        for name in json.loads((folder/'sources.json').read_text(encoding='utf-8'))['raw']:
            raw = Path(name)
            immutable.extend([raw, raw.with_suffix('.json')])
    frozen = json.loads(Path(spec['frozen_manifest']).read_text(encoding='utf-8'))
    for name, expected in frozen.items():
        if digest(Path(name)) != expected:
            raise ValueError('Frozen batch identity differs before publication')
    immutable.extend(Path(name) for name in frozen)
    immutable.extend(Path(spec['prepared_settings']).parent.glob('*.toml'))
    benchmark = tomllib.loads(Path(settings['return_benchmark_config']).read_text(encoding='utf-8'))
    index = root/'clean/equal_weight_indexes'/benchmark['benchmarks']['equal_weight_snapshot']
    immutable.extend(index.glob('*'))
    refresh = tomllib.loads(Path(settings['refresh_config']).read_text(encoding='utf-8'))
    immutable.append(Path(settings['refresh_config']))
    immutable.append(root/'clean/tushare_bulk/snapshots'/refresh['stock_snapshot']/'bar_1d/asset=stock'/f'year={as_of.year}/data.parquet')
    for folder in (root/'clean/tushare_incremental').glob('date=*'):
        if folder.name[5:] <= str(as_of):
            immutable.extend(folder.glob('*.parquet'))
    before = {str(p): digest(p) for p in sorted(set(immutable)) if p.is_file()}
    save(output/'source_manifest_before.json', before)
    dates, frames, receipts = [], [], []
    for folder in daily:
        day = dt.date.fromisoformat(folder.name[5:])
        dates.append(day)
        source = json.loads((folder/'sources.json').read_text(encoding='utf-8'))
        mutable = set()
        for name in source['raw']:
            raw = Path(name)
            kind = raw.parent.parent.name
            if kind in ('stock_basic', 'dividend'):
                meta = json.loads(raw.with_suffix('.json').read_text(encoding='utf-8'))
                if dt.datetime.fromisoformat(meta['fetched_at']).date() < day or digest(raw) != meta['checksum_sha256']:
                    raise ValueError('Mutable facts do not prove daily coverage')
                mutable.add(kind)
        if mutable != {'stock_basic', 'dividend'}:
            raise ValueError('Missing dated company-action or instrument source')
        bars = read_stock_data(data_root=root, config=Path(settings['refresh_config']), table='bar_1d',
            start=day, end=day).select('symbol', 'trade_date', 'volume')
        facts, receipt = daily_open_facts(folder, day, bars)
        frames.append(facts)
        receipts.append(receipt)
    inherited = pl.read_parquet(corrected/'suspension_open_facts.parquet').filter(~pl.col('trade_date').is_in(dates))
    facts = pl.concat([inherited, *frames], how='vertical_relaxed').sort('trade_date', 'symbol')
    old_stops = pl.read_parquet(old/'suspensions.parquet')
    missing = old_stops.join(facts.select('symbol','trade_date'), on=['symbol','trade_date'], how='anti')
    if missing.height or facts.select('symbol', 'trade_date').is_duplicated().any():
        raise ValueError('Old positive suspension keys lost or duplicated')
    blocked = facts.filter(pl.col('open_status') != 'clear_at_open')
    target.mkdir(parents=True, exist_ok=False)
    for name in ('limits.parquet', 'dividends.parquet', 'instruments.parquet', 'sources.json'):
        shutil.copyfile(old/name, target/name)
    blocked.write_parquet(target/'suspensions.parquet')
    facts.write_parquet(target/'suspension_open_facts.parquet')
    save(target/'suspension_receipts.json', receipts)
    save(target/'coverage.json', {'as_of': str(as_of), 'start': '2010-01-01',
        'suspension_policy': POLICY, 'company_actions_and_instruments_inherited_from': old.name,
        'source_coverage_sha256': digest(old/'coverage.json'), 'source_provenance_sha256': digest(old/'sources.json'),
        'mutable_capture_floor': str(_mutable_capture_floor(old)), 'dated_capture_count': len(daily)})
    save(target/'summary.json', {'snapshot': target.name, 'source_month': old.name, 'source_open': corrected.name,
        'suspension_policy': POLICY, 'as_of': str(as_of), 'api_calls': 0, 'auto_trade': False})
    save(target/'source_manifest.json', before)
    policy_of(target)
    # In the current index_day implementation, stopped only labels missing-quote
    # events. Verify every changed key avoids those events; all numeric inputs stay exact.
    added = blocked.select('symbol','trade_date').join(old_stops, on=['symbol','trade_date'], how='anti')
    removed = old_stops.join(blocked.select('symbol','trade_date'), on=['symbol','trade_date'], how='anti')
    changed = pl.concat([added, removed]).unique()
    events = pl.read_parquet(index/'events.parquet')
    affected = events.filter(pl.col('kind').is_in(['suspended_last_mark','missing_quote_last_mark'])).join(
        changed.rename({'trade_date':'date'}), on=['symbol','date'], how='semi')
    if affected.height:
        raise ValueError('Benchmark missing-quote events changed; a new benchmark publication is required')
    for name in ('dividends.parquet', 'instruments.parquet'):
        if digest(old/name) != digest(target/name):
            raise ValueError('Numeric benchmark execution inputs changed')
    proof_paths = [*index.glob('*'), *[folder/name for folder in (old,target)
        for name in ('dividends.parquet','instruments.parquet','suspensions.parquet')], Path('src/quant/data/equal_weight_index.py')]
    proof = {'execution_snapshot': target.name, 'source_execution_snapshot': old.name,
        'equal_weight_snapshot': index.name, 'return_series_unchanged': True,
        'added_positive_keys': added.height, 'removed_positive_keys': removed.height,
        'affected_missing_quote_events': affected.height,
        'basis': 'Same numeric inputs and index_day code; stopped only labels missing quotes; no changed key labels a saved missing-quote event',
        'hashes': {str(p): digest(p) for p in proof_paths}}
    proof_path = output/'benchmark_compatibility.json'
    save(proof_path, proof)
    benchmark['execution_binding'] = {'execution_snapshot': target.name, 'proof': str(proof_path), 'proof_sha256': digest(proof_path)}
    _write_toml(output/'return_benchmarks.toml', benchmark)
    # Independent configuration copies do not make future runs depend on batch 68.
    for key, name in [('battery_config','battery.toml'), ('measurement_config','measurement.toml')]:
        shutil.copyfile(settings[key], output/name)
        settings[key] = str(output/name)
    settings.update(execution_snapshot=target.name, return_benchmark_config=str(output/'return_benchmarks.toml'))
    validate_binding(settings, root)
    remaining = inspect_month_inputs(settings=settings, as_of=as_of)
    if remaining:
        raise ValueError(f'Published monthly inputs incomplete: {remaining}')
    after = {name: digest(Path(name)) for name in before}
    if before != after:
        raise ValueError('Immutable sources changed during publication')
    save(output/'source_manifest_after.json', after)
    save(output/'settings.json', settings)
    result = {'snapshot': target.name, 'as_of': str(as_of), 'old_positive_keys': old_stops.height,
        'new_blocking_or_unknown_keys': blocked.height, 'status_counts': facts.group_by('open_status','open_reason').len().to_dicts(),
        'daily_captures_reused': len(daily), 'all_daily_negative_coverage_verified': all(r['negative_coverage_verified'] for r in receipts),
        'source_hashes_unchanged': True, 'benchmark_return_series_unchanged': True, 'missing': remaining,
        'api_calls': 0, 'account_runs': 0, 'battery_runs': 0, 'auto_trade': False}
    save(output/'summary.json', result)
    (output/'report.md').write_text('# 月度开盘执行版本\n\n```json\n'+json.dumps(result,ensure_ascii=False,indent=2)+'\n```\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    print(json.dumps(publish(**vars(parser.parse_args())), ensure_ascii=False))
