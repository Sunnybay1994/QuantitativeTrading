"""Versioned, bounded corporate-action repair of a frozen fractional benchmark.

The saved source index is reproduced in each affected block before any corrected
version is published. Strategy accounts are read only by the separate evaluator.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil
import tomllib

import polars as pl

from quant.data.equal_weight_actions import action_index_day, validate_exchanges
from quant.data.equal_weight_index import index_day
from quant.data.refresh_stocks import read_stock_data


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding='utf-8')


def scale_event(row: dict, scale: float) -> dict:
    """A local block's absolute units must use the published continuous NAV scale."""
    result = dict(row)
    for key in ('successor_units', 'existing_successor_units', 'merged_successor_units',
                'book_value', 'value_before', 'value_after', 'liquid_opening_capital'):
        if result.get(key) is not None:
            result[key] *= scale
    return result


def blocks_for(series: pl.DataFrame, exchanges: list[dict], proof: int) -> list[tuple]:
    sessions = series['trade_date'].to_list()
    rebalances = series.filter(pl.col('rebalance'))['trade_date'].to_list()
    intervals = []
    for event in exchanges:
        low = max(d for d in rebalances if d < event['effective_date'])
        latest = max(n['tradable_date'] for n in event['listing_notices'])
        sync = min(d for d in rebalances if d >= latest)
        high = sessions[min(len(sessions) - 1, sessions.index(sync) + proof)]
        intervals.append((low, high, sync))
    merged = []
    for low, high, sync in sorted(intervals):
        if merged and low <= merged[-1][1]:
            a, b, c = merged.pop()
            merged.append((a, max(b, high), max(c, sync)))
        else:
            merged.append((low, high, sync))
    return merged


def _source_evidence(settings: dict) -> set[Path]:
    """Recheck fact-file-linked PDF bytes and event ratios, preserving unknown dates."""
    paths, facts = set(), {}
    for name in settings['fact_files']:
        path = Path(name)
        paths.add(path)
        result = json.loads(path.read_text(encoding='utf-8'))
        sources = result['sources'].values() if isinstance(result['sources'], dict) else result['sources']
        for receipt in sources:
            pdf = path.parent / 'sources' / receipt['path']
            if sha(pdf) != receipt['sha256']:
                raise ValueError(f'Changed original PDF: {pdf}')
            paths.add(pdf)
        for fact in result['facts']:
            facts[fact.get('symbol', fact.get('from_symbol'))] = fact
    for e in settings['exchanges']:
        fact = facts[e['from_symbol']]
        if e['ratio'] != fact.get('ratio', fact.get('ratio_new_shares_per_old_share')):
            raise ValueError('Exchange ratio differs from verified facts')
        effective = fact.get('delist', fact.get('delist_date'))
        if str(e['effective_date']) != effective:
            raise ValueError('Recognition date differs from verified delisting')
    return paths


def repair(config: Path, data_root: Path) -> dict:
    settings = tomllib.loads(config.read_text(encoding='utf-8'))
    if settings.get('auto_trade') is not False:
        raise ValueError('Research repair requires auto_trade=false')
    validate_exchanges(settings['exchanges'])
    original = data_root / 'clean/equal_weight_indexes' / settings['original_version']
    destination = data_root / 'clean/equal_weight_indexes' / settings['version']
    output = Path(settings['artifact_root'])
    if destination.exists() or output.exists():
        raise FileExistsError('Use an unused repair version and output directory')
    for key in ('original_version', 'version'):
        if Path(settings[key]).name != settings[key] or settings[key] in ('.', '..'):
            raise ValueError('Invalid version path')
    evidence = _source_evidence(settings)
    old_summary = json.loads((original / 'summary.json').read_text(encoding='utf-8'))
    source_config = Path(settings['original_config'])
    original_settings = tomllib.loads(source_config.read_text(encoding='utf-8'))
    execution = data_root / 'clean/stock_execution' / old_summary['execution_snapshot']
    source_paths = evidence | set(original.glob('*')) | {config, source_config}
    source_paths |= {execution / n for n in ('instruments.parquet', 'dividends.parquet', 'suspensions.parquet')}
    source_paths |= {Path(__file__), Path('src/quant/data/equal_weight_actions.py'), Path('src/quant/data/equal_weight_index.py')}
    source_paths = {p for p in source_paths if p.is_file()}
    hashes = {str(p): sha(p) for p in sorted(source_paths)}
    output.mkdir(parents=True)
    (output / 'inputs').mkdir()
    shutil.copyfile(config, output / 'config.toml')
    write_json(output / 'registration.json', dict(registered_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                                                config_sha256=sha(config), source_hashes=hashes,
                                                stage='rules_frozen_before_repair_results'))
    data = pl.read_parquet(original / 'data.parquet').sort('index_name', 'trade_date')
    old_events = pl.read_parquet(original / 'events.parquet')
    zero = old_events.filter(pl.col('kind') == 'delist_zero_recovery')
    if set(zero['symbol']) != {e['from_symbol'] for e in settings['exchanges']}:
        raise ValueError('Verified exchange scope does not match original zero-recovery records')
    dividends = pl.read_parquet(execution / 'dividends.parquet')
    if dividends.select('symbol', 'ex_date').is_duplicated().any():
        raise ValueError('Ambiguous source dividends')
    stopped_frame = pl.read_parquet(execution / 'suspensions.parquet')
    instruments = pl.read_parquet(execution / 'instruments.parquet')
    delisted = dict(instruments.select('symbol', 'delist_date').iter_rows())
    blocks = blocks_for(data.filter(pl.col('index_name') == 'all_market_equal_weight'),
                        settings['exchanges'], settings['proof_sessions'])
    plans = {n: pl.read_parquet(original / f'{n}_selections.parquet') for n in data['index_name'].unique()}
    patches, event_patches, mask_keys = {}, [], set()
    proofs, ledger, differences = [], [], []
    for block_id, (low, high, sync) in enumerate(blocks):
        needed = set().union(*(set(p.filter(pl.col('effective_date').is_between(low, high))['symbol']) for p in plans.values()))
        needed.update(e['to_symbol'] for e in settings['exchanges'] if low <= e['effective_date'] <= high)
        prices = read_stock_data(data_root=data_root, config=source_config, table='bar_1d',
                                 start=low, end=high, symbols=sorted(needed)).select('trade_date', 'symbol', 'open', 'close', 'volume')
        if prices.select('trade_date', 'symbol').is_duplicated().any():
            raise ValueError('Duplicate price keys')
        prices.write_parquet(output / 'inputs' / f'block_{block_id}_prices.parquet')
        history = data_root / 'clean/tushare_bulk/snapshots' / original_settings['stock_snapshot'] / 'bar_1d/asset=stock'
        for year in range(low.year, high.year + 1):
            source_paths.update((history / f'year={year}').glob('*.parquet'))
        for folder in (data_root / 'clean/tushare_incremental').glob('date=*'):
            if str(low) <= folder.name[5:] <= str(high) and (folder / 'bar_1d.parquet').is_file():
                source_paths.add(folder / 'bar_1d.parquet')
        for p in source_paths:
            if str(p) not in hashes:
                hashes[str(p)] = sha(p)
        quote_map = {k[0]: {r['symbol']: r for r in f.iter_rows(named=True)} for k, f in prices.partition_by('trade_date', as_dict=True).items()}
        action_map = {k[0]: {r['symbol']: r for r in f.iter_rows(named=True)} for k, f in
                      dividends.filter(pl.col('ex_date').is_between(low, high)).partition_by('ex_date', as_dict=True).items()}
        stop_map = {k[0]: set(f['symbol']) for k, f in
                    stopped_frame.filter(pl.col('trade_date').is_between(low, high)).partition_by('trade_date', as_dict=True).items()}
        for name, plan in plans.items():
            schedule = {k[0]: {r['symbol']: r for r in f.iter_rows(named=True)} for k, f in
                        plan.filter(pl.col('effective_date').is_between(low, high)).partition_by('effective_date', as_dict=True).items()}
            old_state, new_state = {}, {}
            max_error, max_sync_weight_error, post_errors = 0., 0., []
            original_rows = data.filter((pl.col('index_name') == name) & pl.col('trade_date').is_between(low, high))
            for saved in original_rows.iter_rows(named=True):
                day = saved['trade_date']
                args = dict(date=day, quotes=quote_map.get(day, {}), actions=action_map.get(day, {}),
                            delisted=delisted, stopped=stop_map.get(day, set()), targets=schedule.get(day))
                if day == low:
                    old_state, _, _ = index_day(state={}, **args)
                    old_state['level'] = saved['index_level']
                    new_state = copy.deepcopy(old_state)
                    continue
                prior_new = new_state['level']
                old_state, old_row, _ = index_day(state=old_state, **args)
                new_state, new_row, new_events = action_index_day(state=new_state, exchanges=settings['exchanges'], **args)
                error = abs(old_row['daily_return'] - saved['daily_return'])
                max_error = max(max_error, error)
                if error > settings['baseline_absolute_tolerance']:
                    raise ValueError(f'Original daily return does not reproduce: {name} {day} {error}')
                weight_error = abs(sum(new_state['weights'].values()) - 1.)
                if weight_error > 1e-10:
                    raise ValueError('Corrected weight sum differs from one')
                if day >= sync:
                    if new_state.get('pending_claims'):
                        raise ValueError('Pending claim remains at planned synchronization; extend facts, not prices')
                    keys = set(old_state['weights']) | set(new_state['weights'])
                    delta = max(abs(old_state['weights'].get(s, 0.) - new_state['weights'].get(s, 0.)) for s in keys)
                    max_sync_weight_error = max(max_sync_weight_error, delta)
                    if delta > 1e-11 or old_state['last'] != new_state['last']:
                        raise ValueError('Weights/marks failed actual resynchronization')
                    if day > sync:
                        post_errors.append(abs(new_row['daily_return'] - old_row['daily_return']))
                differences.append(dict(block=block_id, index_name=name, date=day,
                    original_daily_return=saved['daily_return'], reproduced_daily_return=old_row['daily_return'],
                    repaired_daily_return=new_row['daily_return'], difference=new_row['daily_return'] - saved['daily_return'],
                    pending_claim_weight=new_row['pending_claim_weight'], pending_claim_count=new_row['pending_claim_count']))
                patches[name, day] = {**new_row, 'opening_gross': new_row['opening_index_level'] / prior_new}
                mask_keys.add((name, day))
                event_patches.extend(dict(index_name=name, **e) for e in new_events)
                for claim, item in new_state.get('pending_claims', {}).items():
                    ledger.append(dict(block=block_id, index_name=name, date=day, claim=claim,
                        from_symbol=item['from_symbol'], to_symbol=item['to_symbol'],
                        successor_units=item['units'], book_value=item['book_value'],
                        portfolio_level=new_state['level'], weight=new_state['weights'][claim]))
            if len(post_errors) < settings['proof_sessions'] or max(post_errors, default=1.) > 1e-11:
                raise ValueError('Insufficient matching post-synchronization sessions')
            proofs.append(dict(block=block_id, index_name=name, start=low, end=high, synchronized_on=sync,
                               reproduced_sessions=original_rows.height - 1, max_baseline_daily_error=max_error,
                               max_synchronized_weight_error=max_sync_weight_error,
                               post_sync_sessions=len(post_errors), max_post_sync_return_error=max(post_errors)))
        print(f'Validated block {block_id}: {low}..{high}', flush=True)
    pl.DataFrame(differences).write_parquet(output / 'daily_block_differences.parquet')
    write_json(output / 'synchronization_proofs.json', proofs)
    repaired_rows = []
    block_scales = {}
    for name in sorted(plans):
        level, original_prior = 1000., 1000.
        for original_row in data.filter(pl.col('index_name') == name).iter_rows(named=True):
            r = dict(original_row)
            patch = patches.get((name, r['trade_date']))
            gross_open = r['opening_index_level'] / original_prior
            original_prior = r['index_level']
            r.update(pending_claim_value=0., pending_claim_weight=0., pending_claim_count=0)
            if patch:
                if abs(patch['daily_return'] - r['daily_return']) > 1e-13:
                    r['daily_return'] = patch['daily_return']
                gross_open = patch['opening_gross']
                for k in ('constituents', 'weight_sum', 'missing_quote_weight', 'pending_claim_weight', 'pending_claim_count'):
                    r[k] = patch[k]
            r['opening_index_level'] = level * gross_open
            level *= 1 + r['daily_return']
            r['index_level'] = level
            r['pending_claim_value'] = level * r['pending_claim_weight']
            if patch:
                block_scales[name, r['trade_date']] = level / patch['index_level']
            repaired_rows.append(r)
    repaired = pl.DataFrame(repaired_rows)
    for r in ledger:
        scale = block_scales[r['index_name'], r['date']]
        for key in ('successor_units', 'book_value', 'portfolio_level'):
            r[key] *= scale
        r['local_to_published_scale'] = scale
    pl.DataFrame(ledger).write_parquet(output / 'pending_claim_ledger.parquet')
    event_patches = [scale_event(r, block_scales[r['index_name'], r['date']]) for r in event_patches]
    retained = [r for r in old_events.iter_rows(named=True) if (r['index_name'], r['date']) not in mask_keys]
    corrected_events = pl.DataFrame(retained + event_patches, infer_schema_length=None)
    if corrected_events.filter(pl.col('kind') == 'delist_zero_recovery').height:
        raise ValueError('Unrepaired zero-recovery event remains')
    if not all(sha(Path(p)) == digest for p, digest in hashes.items()):
        raise ValueError('Source changed during bounded repair')
    destination.mkdir(parents=True)
    repaired.write_parquet(destination / 'data.parquet')
    corrected_events.write_parquet(destination / 'events.parquet')
    for name in plans:
        shutil.copyfile(original / f'{name}_selections.parquet', destination / f'{name}_selections.parquet')
    summary = dict(old_summary)
    summary.update(version=settings['version'], previous_version=settings['original_version'],
        rules={**old_summary['rules'], **settings['rules']}, measurement_repair=True,
        pending_value_is_fair_value=False, source_files_unchanged=True, auto_trade=False,
        repair_config_sha256=sha(config), repair_artifacts=str(output),
        events=corrected_events.group_by('index_name', 'kind').len().sort('index_name', 'kind').to_dicts())
    write_json(destination / 'summary.json', summary)
    write_json(output / 'source_manifest.json', dict(sources_sha256=hashes,
        outputs_sha256={str(p): sha(p) for p in destination.glob('*')}, original_files_unchanged=True))
    result = dict(status='benchmark_published', output=str(destination), artifact_root=str(output),
                  original_event_count=zero.height, exchanges=len(settings['exchanges']),
                  blocks=len(blocks), proofs=proofs, account_replays=0, auto_trade=False,
                  evaluation='not_yet_run')
    write_json(output / 'repair_summary.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    args = parser.parse_args()
    result = repair(args.config, args.data_root)
    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()
