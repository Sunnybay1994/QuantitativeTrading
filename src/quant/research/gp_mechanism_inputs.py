"""Freeze all existing PIT financial terminals and audit label-free input coverage.

The mechanism declaration is written before inspecting monthly coverage. Every
declared terminal is retained; actual sampled-group paired-label qualification
continues to belong to the registered GP evaluator.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import datetime as dt
import hashlib
import json
from pathlib import Path
import tomllib

import polars as pl

from quant.data.factor_panels import available_sessions
from quant.factors.library import load_library
from quant.research.factor_battery_evaluation import score_factor_sections
from quant.research.gp_predictive_priority import MechanismManifest, MechanismTerminal


AVAILABILITY = (
    'Existing compute/PIT contract: statement available_date=max(ann_date,f_ann_date), '
    'indicator available_date=ann_date; only available_date strictly before the signal '
    'session is known. Latest known revisions are selected and conflicting economics '
    'quarantined; event updates carry invalid new values rather than filling through them. '
    'Recent incremental publications also delay newly observed economic rows to observation '
    'date. This freezes existing materialized factor values, not an independent audit of '
    'historical provider revision completeness or proof of each partition upstream snapshot.'
)


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=True).encode()).hexdigest()


def file_record(path: Path) -> dict:
    if not path.is_file():
        return {'path': str(path), 'exists': False, 'hash_scope': 'entire_file'}
    before = path.stat()
    with path.open('rb') as stream:
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f'Input changed while hashing: {path}')
    return {'path': str(path), 'exists': True, 'bytes': after.st_size,
            'sha256': checksum, 'hash_scope': 'entire_file'}


def input_version(source: dict) -> str:
    payload = {key: source[key] for key in ('factor_id', 'expression', 'direction', 'partitions')}
    return 'sha256:'+canonical_hash(payload)


def read_mechanism_document(path: Path) -> dict:
    """Expand source shards after checking their entire-file hashes and relative paths."""
    saved = json.loads(path.read_text(encoding='utf-8'))
    version = saved.get('schema_version')
    if version == 'gp_mechanism_inputs_v1':
        return saved
    if version != 'gp_mechanism_inputs_v2' or 'terminal_sources' in saved:
        raise ValueError('Unknown or mixed mechanism declaration format')
    records = saved.get('source_shards')
    if not isinstance(records, list) or not records:
        raise ValueError('Sharded declaration requires source shards')
    sources, seen = {}, set()
    for record in records:
        relative = Path(record['path'])
        resolved = (path.parent/relative).resolve()
        if (relative.is_absolute() or '..' in relative.parts
                or not resolved.is_relative_to(path.parent.resolve()) or resolved in seen):
            raise ValueError('Source shard paths must be distinct and inside the manifest directory')
        seen.add(resolved)
        content = resolved.read_bytes()
        if hashlib.sha256(content).hexdigest() != record['sha256']:
            raise ValueError(f'Source shard content changed: {relative}')
        shard = json.loads(content.decode('utf-8'))
        if shard.get('schema_version') != 'gp_mechanism_sources_v1':
            raise ValueError('Unknown mechanism source shard format')
        addition = shard.get('terminal_sources')
        if not isinstance(addition, dict) or not addition or sources.keys() & addition.keys():
            raise ValueError('Empty or duplicate mechanism source shard entries')
        sources.update(addition)
    if set(sources) != {t['terminal_id'] for t in saved['terminals']}:
        raise ValueError('Source shards do not cover exactly the declared terminals')
    return {**saved, 'terminal_sources': sources}


def write_sharded_manifest(document: dict, path: Path) -> dict:
    """Store the same declaration as <=8-terminal shards; no research reselection."""
    sources = document['terminal_sources']
    ids = sorted(sources)
    if not ids:
        raise ValueError('Cannot shard an empty mechanism declaration')
    payloads, shard_records = [], []
    for index, offset in enumerate(range(0, len(ids), 8)):
        name = f'sources_{index}.json'
        shard = {'schema_version': 'gp_mechanism_sources_v1',
                 'terminal_sources': {key: sources[key] for key in ids[offset:offset+8]}}
        encoded = json.dumps(shard, ensure_ascii=False, indent=2).encode('utf-8')
        shard_records.append({'path': name, 'sha256': hashlib.sha256(encoded).hexdigest()})
        payloads.append((path.parent/name, encoded))
    main = {k: v for k, v in document.items() if k not in ('terminal_sources', 'source_shards')}
    main.update(schema_version='gp_mechanism_inputs_v2', source_shards=shard_records)
    payloads.append((path, json.dumps(main, ensure_ascii=False, indent=2).encode('utf-8')))
    for target, content in payloads:
        if target.exists():
            raise FileExistsError(f'Preserve frozen manifest file: {target}')
        if len(content.splitlines()) >= 1500:
            raise ValueError(f'Mechanism manifest file must stay below 1500 lines: {target}')
    path.parent.mkdir(parents=True, exist_ok=True)
    for target, content in payloads:
        target.write_bytes(content)
    return read_mechanism_document(path)


def load_mechanism_manifest(path: Path, *, verify_sources: bool = True,
                            library: Path | None = None) -> MechanismManifest:
    """Validate immutable declarations; optional source verification is full-file hashing."""
    saved = read_mechanism_document(path)
    manifest = MechanismManifest(tuple(MechanismTerminal(**r) for r in saved['terminals']))
    if manifest.sha256 != saved['manifest_sha256']:
        raise ValueError('Mechanism manifest content changed')
    if set(saved['terminal_sources']) != {t.terminal_id for t in manifest.terminals}:
        raise ValueError('Mechanism declaration and sources differ')
    current = {d.id: d for d in load_library(library)} if library is not None else None
    for terminal in manifest.terminals:
        source = saved['terminal_sources'][terminal.terminal_id]
        if (terminal.terminal_id != 'gp_'+source['factor_id'] or source['family'] != 'pit_financial'
                or terminal.mechanism != 'financial' or terminal.input_version != input_version(source)):
            raise ValueError(f'Mechanism source declaration changed: {terminal.terminal_id}')
        if current is not None:
            definition = current.get(source['factor_id'])
            if definition is None or (definition.expr, definition.direction, definition.family) != (
                    source['expression'], source['direction'], source['family']):
                raise ValueError(f'Current library changed: {terminal.terminal_id}')
        if verify_sources:
            for record in source['partitions']:
                observed = file_record(Path(record['path']))
                if observed != {k: v for k, v in record.items() if k != 'year'}:
                    raise ValueError(f'Frozen mechanism source changed: {record["path"]}')
    return manifest


def month_ends(sessions: tuple[dt.date, ...], start: dt.date, end: dt.date) -> list[dt.date]:
    result = {}
    for day in sorted(set(sessions)):
        if start <= day <= end:
            result[(day.year, day.month)] = day
    return sorted(result.values())


def monthly_coverage(values: pl.DataFrame, universe: pl.DataFrame, *, terminal_id: str,
                     expected_dates: list[dt.date], settings: dict, direction: int) -> list[dict]:
    """Input coverage is not the evaluator's coverage of finite forward labels."""
    keys = ['trade_date', 'symbol']
    values = values.rename({'ts_code': 'symbol'}).select(*keys, 'value')
    for frame in (values, universe):
        if frame.select(pl.struct(keys).is_duplicated().any()).item():
            raise ValueError('Duplicate input coverage keys')
    eligible = universe.filter(pl.col('eligible')).select(*keys, 'industry_l1')
    joined = eligible.join(values, on=keys, how='left', validate='1:1')
    base = {r['trade_date']: r for r in joined.group_by('trade_date').agg(
        pl.len().alias('eligible_symbols'), pl.col('value').is_finite().sum().alias('source_finite'),
        pl.col('industry_l1').is_null().sum().alias('eligible_industry_missing')).to_dicts()}
    scored = score_factor_sections(universe=universe, values=values,
                                   direction=direction, settings=settings)
    counts = {r['trade_date']: r for r in scored.group_by('trade_date').agg(
        *[pl.col(v).is_finite().sum().alias(v) for v in settings['variants']]).to_dicts()}
    rows = []
    for day in expected_dates:
        b, count = base.get(day, {}), counts.get(day, {})
        eligible_count = b.get('eligible_symbols', 0)
        for variant in ('source_value', *settings['variants']):
            finite = b.get('source_finite', 0) if variant == 'source_value' else count.get(variant, 0)
            rows.append({'terminal_id': terminal_id, 'trade_date': day, 'variant': variant,
                'eligible_symbols': eligible_count, 'finite_symbols': finite,
                'finite_fraction_of_eligible': finite/eligible_count if eligible_count else None,
                'eligible_industry_missing': b.get('eligible_industry_missing', 0),
                'at_least_100_input_symbols': finite >= 100,
                'paired_label_coverage': None, 'training_group_qualified': None})
    return rows


def _snapshot_evidence(data_root: Path, config: Path, label: str) -> dict:
    cfg = tomllib.loads(config.read_text(encoding='utf-8'))
    snapshot = cfg.get('financial_snapshot')
    if not isinstance(snapshot, str) or Path(snapshot).name != snapshot:
        raise ValueError('Financial refresh snapshot must be an explicit local name')
    summary = data_root/'clean/tushare_financials'/snapshot/'summary.json'
    metadata = json.loads(summary.read_text(encoding='utf-8')) if summary.exists() else {}
    return {'context': label, 'refresh_config': file_record(config), 'financial_snapshot': snapshot,
            'snapshot_summary': file_record(summary),
            'snapshot_metadata': {k: metadata.get(k) for k in ('name', 'base_version', 'period', 'pit_rule')},
            'financial_share_changes_snapshot': cfg.get('financial_share_changes_snapshot'),
            'partition_upstream_identity_proven': False,
            'scope': 'Observed configuration/publication context, not cached-partition upstream lineage'}


def freeze_declaration(*, data_root: Path, library: Path, reference: Path, battery_config: Path,
                       refresh_config: Path, start: dt.date, end: dt.date,
                       output: Path, manifest_path: Path, expected_terminals: int = 32) -> dict:
    """Freeze the family-defined set and actual sources before examining coverage."""
    if output.exists() or manifest_path.exists():
        raise FileExistsError('Use new declaration/output paths; existing freezes are not overwritten')
    definitions = load_library(library)
    selected = [d for d in definitions if d.family == 'pit_financial']
    if len(selected) != expected_terminals:
        raise ValueError(f'Expected exactly {expected_terminals} predeclared financial terminals')
    terminals, sources = [], {}
    for definition in selected:
        definition_path = data_root/'factors'/definition.id/'definition.json'
        cached = json.loads(definition_path.read_text(encoding='utf-8'))
        if cached != asdict(definition):
            raise ValueError(f'Cached factor definition differs: {definition.id}')
        terminal_id = 'gp_'+definition.id
        source = {'factor_id': definition.id, 'expression': definition.expr,
            'direction': definition.direction, 'family': definition.family, 'source_ref': definition.source_ref,
            'cached_definition': file_record(definition_path),
            'partitions': [{'year': y, **file_record(data_root/'factors'/definition.id/f'year={y}'/'data.parquet')}
                           for y in range(start.year, end.year+1)],
            'upstream_evidence': 'financial_publication_context',
            'partition_upstream_snapshot': None,
            'limitation': 'Cached definition/coverage and compute receipts do not identify the upstream '
                          'financial snapshot for each historical partition. Freeze values, not reconstructed lineage.'}
        sources[terminal_id] = source
        terminals.append(MechanismTerminal(terminal_id, 'financial', input_version(source), AVAILABILITY))
    mechanism = MechanismManifest(tuple(terminals))
    battery = tomllib.loads(battery_config.read_text(encoding='utf-8'))
    historical_refresh = Path(battery['data']['refresh_config'])
    code = ['data/financial_clean.py', 'data/financial_pit.py', 'data/financial_repository.py',
            'data/factor_panels.py', 'factors/compute.py', 'research/factor_financials.py',
            'research/factor_battery_evaluation.py', 'research/factor_battery_statistics.py',
            'research/gp_mechanism_inputs.py']
    code_root = Path(__file__).resolve().parents[1]
    document = {'schema_version': 'gp_mechanism_inputs_v1',
        'frozen_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'selection': {'family': 'pit_financial', 'library_count_at_freeze': len(definitions),
            'terminal_count': len(selected), 'all_matching_terminals_retained': True,
            'uses_ic_returns_or_backtests': False, 'declaration_precedes_monthly_coverage_audit': True},
        'audit_window': {'start': str(start), 'end': str(end),
            'hash_scope': 'Entire data.parquet files for every intersecting year; may contain dates outside audit window',
            'coverage_scope': 'Calendar-derived month-end dates inside the audit window only'},
        'terminals': [asdict(t) for t in terminals], 'manifest_sha256': mechanism.sha256,
        'terminal_sources': sources,
        'financial_publication_context': [
            _snapshot_evidence(data_root, historical_refresh, 'battery_refresh_configuration_observed_now'),
            _snapshot_evidence(data_root, refresh_config, 'current_daily_refresh_configuration_observed_now')],
        'availability_code': [file_record(code_root/p) for p in code],
        'coverage_inputs': {'battery': file_record(battery_config),
            'calendars': [file_record(data_root/f'clean/trade_calendar/market={m}/data.parquet') for m in ('SH', 'SZ')],
            'universes': [file_record(reference/'inputs'/str(y)/'universe.parquet')
                          for y in range(start.year, end.year+1)]},
        'coverage_artifact': str(output/'coverage.json'),
        'limitations': ['No independent reconstruction or validation of historical financial revision vintages.',
            'F-score additionally depends on share-change event coverage; insufficient terminals remain declared.',
            'Industry history before 2014 is not backfilled; neutral input coverage is reported separately.',
            'Finite fraction of eligible stocks is not finite-label paired coverage.',
            'The 48-month/100-stock/0.8 criteria apply later to each frozen training group with labels; no label-free pass is asserted.']}
    output.mkdir(parents=True, exist_ok=False)
    write_sharded_manifest(document, output/'manifest.json')
    return write_sharded_manifest(document, manifest_path)


def audit_coverage(*, declaration: dict, manifest_path: Path, data_root: Path,
                   reference: Path, output: Path) -> dict:
    start, end = (dt.date.fromisoformat(declaration['audit_window'][k]) for k in ('start', 'end'))
    expected = month_ends(available_sessions(data_root, end), start, end)
    settings = tomllib.loads(Path(declaration['coverage_inputs']['battery']['path']).read_text(encoding='utf-8'))
    monthly_universes = {}
    for year in range(start.year, end.year+1):
        days = [d for d in expected if d.year == year]
        monthly_universes[year] = pl.scan_parquet(reference/'inputs'/str(year)/'universe.parquet').filter(
            pl.col('trade_date').is_in(days)).select('trade_date', 'symbol', 'eligible',
                                                 'total_market_value', 'industry_l1').collect()
    rows = []
    for index, terminal in enumerate(declaration['terminals'], 1):
        terminal_id = terminal['terminal_id']
        source = declaration['terminal_sources'][terminal_id]
        for partition in source['partitions']:
            year = partition['year']
            days = [d for d in expected if d.year == year]
            values = (pl.scan_parquet(partition['path']).filter(pl.col('trade_date').is_in(days)).select(
                'trade_date', 'ts_code', 'value').collect() if partition['exists'] else
                pl.DataFrame(schema={'trade_date': pl.Date, 'ts_code': pl.String, 'value': pl.Float64}))
            rows.extend(monthly_coverage(values, monthly_universes[year], terminal_id=terminal_id,
                                         expected_dates=days, settings=settings, direction=source['direction']))
        print(json.dumps({'terminal': terminal_id, 'completed': index,
                          'total': len(declaration['terminals'])}), flush=True)
    table = pl.from_dicts(rows)
    # Verify original files again after reads; background changes invalidate this audit.
    load_mechanism_manifest(manifest_path, verify_sources=True)
    coverage_sources = declaration['coverage_inputs']
    for record in [coverage_sources['battery'], *coverage_sources['calendars'], *coverage_sources['universes']]:
        if file_record(Path(record['path'])) != record:
            raise ValueError(f'Coverage input changed: {record["path"]}')
    summaries = []
    for terminal in declaration['terminals']:
        subset = table.filter(pl.col('terminal_id') == terminal['terminal_id'])
        variants = {}
        for variant in subset['variant'].unique().sort().to_list():
            frame = subset.filter(pl.col('variant') == variant)
            variants[variant] = {'months': frame.height, 'zero_finite_months': frame.filter(
                pl.col('finite_symbols') == 0).height, 'months_at_least_100_input_symbols':
                frame['at_least_100_input_symbols'].sum(),
                'minimum_finite_symbols': frame['finite_symbols'].min(),
                'maximum_finite_symbols': frame['finite_symbols'].max(),
                'first_month_at_least_100': str(frame.filter(pl.col('at_least_100_input_symbols'))[
                    'trade_date'].min()) if frame['at_least_100_input_symbols'].any() else None}
        summaries.append({'terminal_id': terminal['terminal_id'], 'retained_in_manifest': True,
                          'variants': variants, 'training_group_qualified': None})
    path = output/'monthly_coverage.parquet'
    table.write_parquet(path)
    result = {'status': 'complete', 'manifest_path': str(manifest_path),
        'manifest_file_sha256': file_record(manifest_path)['sha256'],
        'mechanism_manifest_sha256': declaration['manifest_sha256'],
        'terminal_count': len(summaries), 'declared_terminal_count': len(declaration['terminals']),
        'dropped_terminals': [], 'return_labels_read': False, 'used_ic_returns_or_backtests': False,
        'expected_months': len(expected), 'first_month': str(expected[0]), 'last_month': str(expected[-1]),
        'coverage_rows': table.height, 'coverage_file': file_record(path),
        'terminal_summaries': summaries, 'all_source_hashes_unchanged_after_audit': True,
        'actual_training_criteria': {'minimum_valid_months_per_group': 48,
            'minimum_symbols_per_month': 100, 'minimum_paired_coverage': .8,
            'evaluated_here': False, 'reason': 'No training groups or future-return labels read'},
        'limitations': declaration['limitations']}
    (output/'coverage.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--library', type=Path, default=Path('configs/factors/library'))
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--battery', type=Path, required=True)
    parser.add_argument('--refresh', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    declaration = freeze_declaration(data_root=args.data_root, library=args.library,
        reference=args.reference, battery_config=args.battery, refresh_config=args.refresh,
        start=dt.date(2010, 1, 1), end=dt.date(2026, 8, 31), output=args.output, manifest_path=args.manifest)
    result = audit_coverage(declaration=declaration, manifest_path=args.manifest,
        data_root=args.data_root, reference=args.reference, output=args.output)
    print(json.dumps({k: result[k] for k in ('status', 'terminal_count', 'expected_months', 'coverage_rows')}))


if __name__ == '__main__':
    main()
