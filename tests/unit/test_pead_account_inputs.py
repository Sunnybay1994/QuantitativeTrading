import datetime as dt
import hashlib
import json
from pathlib import Path

import polars as pl
import pytest

from quant.research import pead_account_inputs as module


DAY = dt.date(2019, 12, 13)
EVIDENCE = [{'url': module.ALIAS_URL, 'finding': '000043 to 001914; unchanged entity and share count'}]


def bars(day=DAY):
    return pl.DataFrame({'symbol': ['000043.SZ', '001914.SZ'], 'trade_date': [day]*2,
        'open': [10.0]*2, 'high': [11.0]*2, 'low': [9.0]*2, 'close': [10.0]*2,
        'volume': [100.0]*2, 'amount': [1000.0]*2, 'adj_factor': [2.0]*2, 'source': ['fixture']*2})


def limits(day=DAY):
    return pl.DataFrame({'symbol': ['000043.SZ'], 'trade_date': [day],
                         'up_limit': [11.0], 'down_limit': [9.0]})


def test_manifest_order_preserves_increment_precedence_and_full_schema(tmp_path):
    history, increment = tmp_path/'history.parquet', tmp_path/'increment.parquet'
    bars().write_parquet(history)
    bars().head(1).with_columns(pl.lit(10.5).alias('close')).write_parquet(increment)
    result = module._resolve_market_bars([history, increment], start=DAY, end=DAY,
                                         symbols={'000043.SZ', '001914.SZ'})
    assert result.columns == module.BAR_COLUMNS
    assert result.filter(pl.col('symbol') == '000043.SZ')['close'].item() == 10.5
    assert result['adj_factor'].to_list() == [2.0, 2.0]


def test_duplicate_rows_inside_one_source_never_get_silently_deduplicated(tmp_path):
    path = tmp_path/'duplicate.parquet'
    pl.concat([bars(), bars().head(1)]).write_parquet(path)
    with pytest.raises(ValueError, match='Duplicate daily keys'):
        module._resolve_market_bars([path], start=DAY, end=DAY, symbols={'000043.SZ'})


def test_same_entity_alias_only_fills_verified_missing_pre_change_band():
    updated, receipt = module.fill_same_entity_limits(bars=bars(), limits=limits(), evidence=EVIDENCE)
    assert updated.height == 2
    assert receipt['applied'].to_list() == [True]
    assert updated.filter(pl.col('symbol') == '001914.SZ')['up_limit'].item() == 11.0
    unchanged, empty = module.fill_same_entity_limits(bars=bars(), limits=updated, evidence=EVIDENCE)
    assert unchanged.equals(updated) and empty.is_empty()


@pytest.mark.parametrize('damage', ['close', 'amount', 'missing_old', 'effective_date'])
def test_alias_does_not_invent_bands_when_daily_evidence_does_not_match(damage):
    frame, band = bars(), limits()
    if damage in ('close', 'amount'):
        frame = frame.with_columns(pl.when(pl.col('symbol') == '000043.SZ').then(pl.col(damage)+1)
                                   .otherwise(pl.col(damage)).alias(damage))
    elif damage == 'missing_old':
        frame = frame.filter(pl.col('symbol') != '000043.SZ')
    else:
        frame, band = bars(module.ALIAS_DATE), limits(module.ALIAS_DATE)
    updated, receipt = module.fill_same_entity_limits(bars=frame, limits=band, evidence=EVIDENCE)
    assert updated.equals(band)
    assert receipt['applied'].sum() == 0


def test_alias_requires_official_mapping_evidence():
    with pytest.raises(ValueError, match='official'):
        module.fill_same_entity_limits(bars=bars(), limits=limits(), evidence=[])


def test_zero_missing_and_reversed_bands_are_preserved_as_unusable():
    original = pl.DataFrame({'symbol': ['000001.SZ']*4,
        'trade_date': [DAY+dt.timedelta(days=i) for i in range(4)],
        'up_limit': [11.0, 0.0, None, 9.0], 'down_limit': [9.0, 0.0, 9.0, 11.0]})
    usable, invalid = module._usable_daily_bands(original)
    assert usable.equals(original.head(1)) and invalid.equals(original.tail(3))


def test_terminal_record_date_preserves_future_cash_and_restricted_share_rights():
    end = dt.date(2026, 8, 31)
    original = pl.DataFrame({'symbol': ['000001.SZ']*2,
        'record_date': [end, end+dt.timedelta(days=1)],
        'ex_date': [end+dt.timedelta(days=1), end+dt.timedelta(days=2)],
        'pay_date': [end+dt.timedelta(days=5)]*2, 'share_list_date': [end+dt.timedelta(days=8)]*2})
    result = module._account_dividends(original, symbols={'000001.SZ'}, start=DAY, end=end)
    assert result.equals(original.head(1))


def raw_request(tmp_path, name, params, *, frame=None, count=None):
    root = tmp_path/'raw/tushare/suspend_d/date=2026-09-30'
    root.mkdir(parents=True, exist_ok=True)
    if frame is None:
        frame = pl.DataFrame(schema={'ts_code': pl.String, 'trade_date': pl.String,
            'suspend_timing': pl.String, 'suspend_type': pl.String})
    data = root/f'{name}.parquet'; frame.write_parquet(data)
    metadata = root/f'{name}.json'
    metadata.write_text(json.dumps({'table': 'suspend_d', 'source': 'tushare', 'parameters': params,
        'rows': frame.height if count is None else count, 'columns': frame.columns,
        'checksum_sha256': hashlib.sha256(data.read_bytes()).hexdigest()}))
    return metadata, data


def test_complete_empty_request_proves_only_requested_market_date(tmp_path):
    tomorrow = DAY + dt.timedelta(days=1)
    raw_request(tmp_path, 'global', {'trade_date': DAY.strftime('%Y%m%d')})
    raw_request(tmp_path, 'symbol', {'ts_code': '001914.SZ', 'start_date': DAY.strftime('%Y%m%d'),
        'end_date': tomorrow.strftime('%Y%m%d'), 'suspend_type': 'S'})
    detail, coverage, individual, requests, hashes = module.read_suspensions(
        data_root=tmp_path, sessions=[DAY, tomorrow], symbols={'001914.SZ'})
    assert detail.is_empty()
    assert coverage['coverage_complete'].to_list() == [True, False]
    assert len(individual) == 1 and len(requests) == 2 and len(hashes) == 4


def test_known_partial_halt_is_preserved_and_resume_rows_are_not_halts(tmp_path):
    raw = pl.DataFrame({'ts_code': ['001914.SZ']*2, 'trade_date': [DAY.strftime('%Y%m%d')]*2,
        'suspend_timing': ['09:30-10:00', None], 'suspend_type': ['S', 'R']})
    raw_request(tmp_path, 'daily', {'trade_date': DAY.strftime('%Y%m%d')}, frame=raw)
    detail, coverage, *_ = module.read_suspensions(data_root=tmp_path, sessions=[DAY], symbols={'001914.SZ'})
    assert detail.height == 1 and detail['suspension_scope'].item() == 'PARTIAL'
    assert detail['suspension_detail'].item() == '09:30-10:00'
    assert coverage['coverage_complete'].item() is True


def test_capped_reply_retains_known_halts_but_cannot_prove_coverage(tmp_path):
    raw = pl.DataFrame({'ts_code': ['001914.SZ']*5000, 'trade_date': [DAY.strftime('%Y%m%d')]*5000,
        'suspend_timing': [None]*5000, 'suspend_type': ['S']*5000},
        schema_overrides={'suspend_timing': pl.String})
    raw_request(tmp_path, 'capped', {'trade_date': DAY.strftime('%Y%m%d')}, frame=raw)
    detail, coverage, *_ = module.read_suspensions(data_root=tmp_path, sessions=[DAY], symbols={'001914.SZ'})
    assert detail.height == 1 and coverage['coverage_complete'].item() is False


@pytest.mark.parametrize('damage', ['checksum', 'rows', 'outside_window'])
def test_raw_suspension_bad_receipt_is_not_accepted(tmp_path, damage):
    frame = None
    if damage == 'outside_window':
        frame = pl.DataFrame({'ts_code': ['001914.SZ'], 'trade_date': ['20191212'],
                             'suspend_timing': [None], 'suspend_type': ['S']})
    meta, data = raw_request(tmp_path, 'bad', {'trade_date': '20191213'}, frame=frame,
                             count=1 if damage == 'rows' else None)
    if damage == 'checksum':
        data.write_bytes(b'changed')
    with pytest.raises(ValueError):
        module.read_suspensions(data_root=tmp_path, sessions=[DAY], symbols={'001914.SZ'})


def frozen_identity(tmp_path):
    target = tmp_path/'inputs'; target.mkdir()
    (target/'financial_manifest.json').write_text('{"files": {}}')
    (target/'market_manifest.json').write_text(json.dumps({'financial_manifest_sha256': module._sha(target/'financial_manifest.json')}))
    (target/'eligibility_events.parquet').write_bytes(b'frozen fixture')
    (target/'eligibility_manifest.json').write_text(json.dumps({'events_sha256': module._sha(target/'eligibility_events.parquet')}))
    (target/'eligibility_identity.json').write_text(json.dumps({'market_manifest_sha256': module._sha(target/'market_manifest.json'),
                                                               'events_sha256': 'financial-events-identity'}))
    manifest = {'files': {path.name: module._sha(path) for path in target.iterdir()},
                'financial_events_sha256': 'financial-events-identity'}
    (target/'manifest.json').write_text(json.dumps(manifest))
    return target, manifest


def test_verify_checks_local_frozen_identity_without_reopening_raw(tmp_path):
    target, manifest = frozen_identity(tmp_path)
    assert module.verify_frozen_inputs(output=tmp_path) == manifest
    (target/'eligibility_events.parquet').write_bytes(b'changed')
    with pytest.raises(ValueError, match='Frozen account input changed'):
        module.verify_frozen_inputs(output=tmp_path)


def test_verify_rejects_broken_parent_identity_even_with_refreshed_local_hash(tmp_path):
    target, manifest = frozen_identity(tmp_path)
    (target/'financial_manifest.json').write_text('{"changed":true}')
    manifest['files']['financial_manifest.json'] = module._sha(target/'financial_manifest.json')
    (target/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='parent-stage identity'):
        module.verify_frozen_inputs(output=tmp_path)
