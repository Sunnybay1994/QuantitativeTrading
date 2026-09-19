from dataclasses import asdict
import datetime as dt
import json

import polars as pl
import pytest

from quant.research.gp_mechanism_inputs import (
    file_record, input_version, load_mechanism_manifest, month_ends, monthly_coverage,
    read_mechanism_document, write_sharded_manifest,
)
from quant.research.gp_predictive_priority import MechanismManifest, MechanismTerminal


def test_full_source_hash_and_expression_direction_are_versioned(tmp_path):
    path = tmp_path/'data.parquet'
    path.write_bytes(b'original entire partition')
    source = {'factor_id': 'pit_test', 'expression': 'pit_test', 'direction': 1,
              'family': 'pit_financial', 'partitions': [{'year': 2025, **file_record(path)}]}
    version = input_version(source)
    assert input_version({**source, 'direction': -1}) != version
    assert input_version({**source, 'expression': 'rank(pit_test)'}) != version
    terminal = MechanismTerminal('gp_pit_test', 'financial', version, 'existing PIT rule')
    manifest = MechanismManifest((terminal,))
    document = {'schema_version': 'gp_mechanism_inputs_v1', 'terminals': [asdict(terminal)],
                'terminal_sources': {'gp_pit_test': source}, 'manifest_sha256': manifest.sha256}
    saved = tmp_path/'manifest.json'
    saved.write_text(json.dumps(document))
    assert load_mechanism_manifest(saved).sha256 == manifest.sha256
    split = tmp_path/'split'/'manifest.json'
    expanded = write_sharded_manifest(document, split)
    assert expanded['terminal_sources'] == document['terminal_sources']
    assert load_mechanism_manifest(split).sha256 == manifest.sha256
    path.write_bytes(b'updated later-date rows in same whole partition')
    with pytest.raises(ValueError, match='Frozen mechanism source changed'):
        load_mechanism_manifest(saved)


def test_shard_tampering_and_path_escape_are_rejected(tmp_path):
    document = {'schema_version': 'gp_mechanism_inputs_v1',
                'terminals': [{'terminal_id': 'gp_a'}], 'terminal_sources': {'gp_a': {'value': 1}}}
    target = tmp_path/'bundle'/'manifest.json'
    write_sharded_manifest(document, target)
    shard = target.parent/'sources_0.json'
    original = shard.read_bytes()
    shard.write_bytes(original+b' ')
    with pytest.raises(ValueError, match='Source shard content changed'):
        read_mechanism_document(target)
    shard.write_bytes(original)
    main = json.loads(target.read_text())
    main['source_shards'][0]['path'] = '../sources_0.json'
    target.write_text(json.dumps(main))
    with pytest.raises(ValueError, match='inside the manifest directory'):
        read_mechanism_document(target)


def test_shards_keep_all_entries_and_refuse_overwriting_freeze(tmp_path):
    document = {'schema_version': 'gp_mechanism_inputs_v1',
                'terminals': [{'terminal_id': f'gp_{i}'} for i in range(32)],
                'terminal_sources': {f'gp_{i}': {'value': i} for i in range(32)}}
    target = tmp_path/'manifest.json'
    expanded = write_sharded_manifest(document, target)
    assert expanded['terminal_sources'] == document['terminal_sources']
    assert len(expanded['source_shards']) == 4
    for record in expanded['source_shards']:
        assert len(json.loads((tmp_path/record['path']).read_text())['terminal_sources']) == 8
    with pytest.raises(FileExistsError):
        write_sharded_manifest(document, target)


def test_calendar_month_ends_keep_partial_end_month_explicit():
    days = (dt.date(2020, 1, 30), dt.date(2020, 1, 31), dt.date(2020, 2, 27), dt.date(2020, 2, 28))
    assert month_ends(days, dt.date(2020, 1, 1), dt.date(2020, 2, 27)) == [days[1], days[2]]


def test_no_labels_no_qualification_and_early_industry_gap_remains():
    day, missing = dt.date(2010, 1, 29), dt.date(2010, 2, 26)
    values = pl.DataFrame({'trade_date': [day]*110, 'ts_code': [str(i) for i in range(110)],
                           'value': [float(i) for i in range(110)]})
    universe = values.rename({'ts_code': 'symbol'}).drop('value').with_columns(
        pl.lit(True).alias('eligible'), pl.lit(1e9).alias('total_market_value'),
        pl.lit(None, dtype=pl.String).alias('industry_l1'))
    settings = {'variants': ['raw', 'size_industry_neutral'],
                'preprocessing': {'mad_multiplier': 3., 'mad_normal_scale': 1.4826}}
    rows = monthly_coverage(values, universe, terminal_id='gp_pit_test', expected_dates=[day, missing],
                            settings=settings, direction=1)
    raw = next(r for r in rows if r['variant'] == 'raw' and r['trade_date'] == day)
    neutral = next(r for r in rows if r['variant'] == 'size_industry_neutral' and r['trade_date'] == day)
    assert raw['finite_symbols'] == 110 and neutral['finite_symbols'] == 0
    assert raw['eligible_industry_missing'] == 110
    assert all(r['training_group_qualified'] is None and r['paired_label_coverage'] is None for r in rows)
    assert all(r['finite_symbols'] == 0 for r in rows if r['trade_date'] == missing)
