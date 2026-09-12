import datetime as dt
from pathlib import Path

import polars as pl
import pytest

from quant.data import publish_daily_basic_field_recovery as publisher


DAY = dt.date(2026, 8, 31)


def batch(tmp_path: Path, monkeypatch, *, partial=False):
    root = tmp_path/'data'
    raw = root/'raw'
    raw.mkdir(parents=True)
    paths = {}
    for table in ['daily', 'basic', 'adjustment']:
        paths[table] = raw/f'{table}.parquet'
        pl.DataFrame({'ts_code': ['A', 'B'], 'trade_date': ['20260831']*2}).write_parquet(paths[table])
    keys = tmp_path/'keys.parquet'
    pl.DataFrame({'symbol': ['A', 'B'], 'as_of': [DAY]*2,
        'raw_path': [str(paths['basic'])]*2, 'daily_raw_path': [str(paths['daily'])]*2,
        'adjustment_raw_path': [str(paths['adjustment'])]*2}).write_parquet(keys)
    config = tmp_path/'config.toml'
    config.write_text(f'version="test"\nkeys_file={str(keys.as_posix())!r}\nexpected_rows=2\n')

    def recover(**kwargs):
        symbol = kwargs['basic']['ts_code'].item()
        assert kwargs['date'] == DAY
        if symbol == 'B' and not partial:
            raise ValueError('Independent market-value check failed')
        return pl.DataFrame({'symbol': [symbol], 'trade_date': [DAY], 'close': [10.],
            'total_market_value': [100.], 'daily_basic_schema_valid': [symbol == 'A'],
            'quality_reason': ['free_float_conflict' if symbol == 'A' else 'partial_supplement'],
            'cleared_fields': ['free_float_shares'], 'market_value_relative_difference': [0.]})

    monkeypatch.setattr(publisher, 'recover_daily_basic_fields', recover)
    return root, config, keys, paths


def test_publish_preserves_sources_and_keeps_failed_rows_quarantined(tmp_path, monkeypatch):
    root, config, keys, paths = batch(tmp_path, monkeypatch)
    original = {p: p.read_bytes() for p in [keys, *paths.values()]}
    result = publisher.publish_field_recovery(config=config, data_root=root)
    assert result['requested_rows'] == 2 and result['recovered_rows'] == 1
    assert result['full_schema_rows'] == 1 and result['quarantined_rows'] == 1
    assert publisher.read_field_recovery(data_root=root, version='test')['symbol'].to_list() == ['A']
    rejected = pl.read_parquet(Path(result['output'])/'quarantined.parquet')
    assert rejected['symbol'].to_list() == ['B']
    assert 'Independent market-value' in rejected['quality_reason'].item()
    assert all(p.read_bytes() == content for p, content in original.items())
    with pytest.raises(FileExistsError):
        publisher.publish_field_recovery(config=config, data_root=root)


def test_partial_supplements_require_explicit_reader_opt_in(tmp_path, monkeypatch):
    root, config, _, _ = batch(tmp_path, monkeypatch, partial=True)
    result = publisher.publish_field_recovery(config=config, data_root=root)
    assert result['full_schema_rows'] == result['supplement_only_rows'] == 1
    assert publisher.read_field_recovery(data_root=root, version='test').height == 1
    assert publisher.read_field_recovery(data_root=root, version='test', full_schema_only=False).height == 2


def test_sources_outside_raw_remain_quarantined_and_duplicate_plan_is_rejected(tmp_path, monkeypatch):
    root, config, keys, paths = batch(tmp_path, monkeypatch)
    outside = tmp_path/'outside.parquet'
    outside.write_bytes(paths['basic'].read_bytes())
    plan = pl.read_parquet(keys).with_columns(pl.lit(str(outside)).alias('raw_path'))
    plan.write_parquet(keys)
    result = publisher.publish_field_recovery(config=config, data_root=root)
    assert result['recovered_rows'] == 0 and result['quarantined_rows'] == 2
    config.write_text(config.read_text().replace('"test"', '"second"'))
    pl.concat([plan.head(1), plan.head(1)]).write_parquet(keys)
    with pytest.raises(ValueError, match='unique dated keys'):
        publisher.publish_field_recovery(config=config, data_root=root)
