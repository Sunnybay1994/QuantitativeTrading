import datetime as dt
import hashlib
import json
from pathlib import Path

import polars as pl
import pytest

from quant.data.structured_futures import capture
from quant.reporting.structured_futures import market_facts
from tests.unit.test_structured_incremental import setup, Client


def probe_file(tmp_path, *, observed='2026-11-06T10:00:00+00:00', day='20261106', suffix='one', params=None):
    from quant.data.storage import RawStore
    frame = quotes().with_columns(pl.lit(day).alias('trade_date'))
    raw = RawStore(tmp_path/'raw').write(source='tushare', table='fut_daily', frame=frame,
        parameters=params or {'trade_date': day, 'exchange': 'CFFEX', 'limit': '2000', 'offset': '0'},
        fetched_at=dt.datetime.fromisoformat(observed))
    path = tmp_path/f'probe_{suffix}.json'
    path.write_text(json.dumps({'fut_daily': {'raw_path': str(raw.data_path)}}))
    return path, raw.data_path


def quotes():
    return pl.DataFrame({'ts_code': ['IF2611.CFX', 'IC2611.CFX', 'IM2611.CFX', 'T2611.CFX'],
        'trade_date': ['20261106']*4, 'close': [4000., 5000., 6000., 100.],
        'settle': [4000., 5000., 6000., 100.], 'vol': [1.]*4, 'oi': [1.]*4})


def test_futures_are_monthly_quotes_not_fabricated_basis(tmp_path, monkeypatch):
    setup(tmp_path)
    monkeypatch.setattr('quant.data.structured_incremental._yield_check', lambda *a: None)
    record = capture(data_root=tmp_path, as_of=dt.date(2026, 11, 6), output=tmp_path/'probe',
                     connector=Client(lambda *a: quotes()))
    assert record['rows'] == 3 and record['consumer'] == 'monthly_market_panel_only'
    # This fixture uses root/data convention expected by the reporting module.
    market = tmp_path/'market'
    market.mkdir()
    import shutil
    shutil.copytree(tmp_path/'clean/fut_daily', market/'data/clean/fut_daily')
    known = max(dt.datetime(2026, 11, 10, tzinfo=dt.timezone.utc),
                dt.datetime.fromisoformat(record['observed_at'])+dt.timedelta(seconds=1))
    report = market_facts('2026-11', root=market, known_at=known)
    assert report['status'] == 'observed_quotes'
    assert report['basis_status'].startswith('unknown')
    assert len(report['rows']) == 3
    assert market_facts('2026-11',root=market,known_at=known.astimezone(
        dt.timezone(dt.timedelta(hours=8))))==report
    early = market_facts('2026-11', root=market,
        known_at=dt.datetime(2026, 11, 8, tzinfo=dt.timezone.utc))
    assert early['status'] == 'no_observed_rows_in_month'


def test_futures_scope_and_duplicates_fail_closed(tmp_path, monkeypatch):
    setup(tmp_path)
    monkeypatch.setattr('quant.data.structured_incremental._yield_check', lambda *a: None)
    with pytest.raises(ValueError, match='unique daily contracts'):
        capture(data_root=tmp_path, as_of=dt.date(2026, 11, 6), output=tmp_path/'bad',
                connector=Client(lambda *a: quotes().head(1)))


def test_same_output_basename_different_source_dates_publish_distinct_versions(tmp_path, monkeypatch):
    setup(tmp_path)
    monkeypatch.setattr('quant.data.structured_incremental._yield_check', lambda *a: None)
    first, _ = probe_file(tmp_path)
    second, _ = probe_file(tmp_path, day='20261109', observed='2026-11-09T10:00:00+00:00', suffix='two')
    a = capture(data_root=tmp_path, as_of=dt.date(2026, 11, 6), output=tmp_path/'day1/futures', probe_receipt=first)
    original = (Path(a['clean_path'])/'data.parquet').read_bytes()
    b = capture(data_root=tmp_path, as_of=dt.date(2026, 11, 9), output=tmp_path/'day2/futures', probe_receipt=second)
    assert a['clean_path'] != b['clean_path'] and a['version_sha256'] != b['version_sha256']
    assert (Path(a['clean_path'])/'data.parquet').read_bytes() == original
    assert b['observed_at'] == '2026-11-09T10:00:00+00:00'


def test_identical_raw_is_idempotent_without_new_observation_or_provider_call(tmp_path, monkeypatch):
    setup(tmp_path)
    monkeypatch.setattr('quant.data.structured_incremental._yield_check', lambda *a: None)
    probe, raw = probe_file(tmp_path)
    a = capture(data_root=tmp_path, as_of=dt.date(2026, 11, 6), output=tmp_path/'one/futures', probe_receipt=probe)
    clean = Path(a['clean_path'])/'data.parquet'
    before = clean.read_bytes(), raw.read_bytes()
    client = Client(lambda *a: (_ for _ in ()).throw(AssertionError('no provider call allowed')))
    repeat = capture(data_root=tmp_path, as_of=dt.date(2026, 11, 6), output=tmp_path/'one/futures', connector=client)
    other = capture(data_root=tmp_path, as_of=dt.date(2026, 11, 6), output=tmp_path/'two/futures', probe_receipt=probe)
    assert repeat['reused'] and other['reused'] and not client.calls
    assert a['observed_at'] == repeat['observed_at'] == other['observed_at']
    assert a['available_at'] == repeat['available_at'] == other['available_at']
    assert before == (clean.read_bytes(), raw.read_bytes())


def test_recovery_preserves_old_failed_stage_and_discloses_missing_provider_parameters(tmp_path, monkeypatch):
    setup(tmp_path)
    monkeypatch.setattr('quant.data.structured_incremental._yield_check', lambda *a: None)
    _, raw = probe_file(tmp_path, params={'trade_date': '20261106', 'exchange': 'CFFEX'})
    output = tmp_path/'day/futures'
    stage = output/'clean'
    stage.mkdir(parents=True)
    receipt = {'trade_date': '2026-11-06', 'raw_path': str(raw)}
    (stage/'summary.json').write_text(json.dumps(receipt))
    (stage/'data.parquet').write_bytes(b'prior_failed_attempt_preserved')
    before = {p.name: p.read_bytes() for p in stage.iterdir()}
    client = Client(lambda *a: (_ for _ in ()).throw(AssertionError('must reuse old raw')))
    result = capture(data_root=tmp_path, as_of=dt.date(2026, 11, 6), output=output, connector=client)
    assert not client.calls and result['provider_parameters_complete'] is False
    assert 'limit' not in result['provider_parameters']
    assert before == {p.name: p.read_bytes() for p in stage.iterdir()}
    assert len(list((output/'attempts').glob('*.json'))) == 1


def test_fresh_capture_saves_exact_provider_arguments_and_raw_and_clean_hashes(tmp_path, monkeypatch):
    setup(tmp_path)
    monkeypatch.setattr('quant.data.structured_incremental._yield_check', lambda *a: None)
    client = Client(lambda *a: quotes())
    result = capture(data_root=tmp_path, as_of=dt.date(2026, 11, 6), output=tmp_path/'fresh', connector=client)
    assert result['provider_parameters'] == client.calls[0][1]
    assert result['provider_parameters_complete']
    assert result['raw_sha256'] == hashlib.sha256(Path(result['raw_path']).read_bytes()).hexdigest()
    assert result['clean_sha256'] == hashlib.sha256((Path(result['clean_path'])/'data.parquet').read_bytes()).hexdigest()


def test_same_content_new_actual_observation_is_new_version_and_corruption_fails(tmp_path, monkeypatch):
    setup(tmp_path)
    monkeypatch.setattr('quant.data.structured_incremental._yield_check', lambda *a: None)
    one, _ = probe_file(tmp_path)
    two, _ = probe_file(tmp_path, observed='2026-11-07T10:00:00+00:00', suffix='two')
    a = capture(data_root=tmp_path, as_of=dt.date(2026, 11, 6), output=tmp_path/'a', probe_receipt=one)
    b = capture(data_root=tmp_path, as_of=dt.date(2026, 11, 6), output=tmp_path/'b', probe_receipt=two)
    assert a['raw_sha256'] == b['raw_sha256'] and a['version_sha256'] != b['version_sha256']
    target = Path(a['clean_path'])/'data.parquet'
    target.write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='immutable futures publication differs'):
        capture(data_root=tmp_path, as_of=dt.date(2026, 11, 6), output=tmp_path/'c', probe_receipt=one)
    assert target.read_bytes() == b'corrupt'
    attempt = json.loads(next((tmp_path/'c/attempts').glob('*.json')).read_text())
    assert attempt['status'] == 'failed' and attempt['error_type'] == 'ValueError'


def test_retry_of_new_publish_failure_reuses_cached_raw_and_retains_attempts(tmp_path, monkeypatch):
    from quant.data import structured_futures as module
    setup(tmp_path)
    monkeypatch.setattr('quant.data.structured_incremental._yield_check', lambda *a: None)
    probe, _ = probe_file(tmp_path)
    original = module.publish_directory
    def fail(**kwargs):
        raise PermissionError('fixture publication interruption')
    monkeypatch.setattr(module, 'publish_directory', lambda *a, **kw: fail(**kw))
    out = tmp_path/'retry/futures'
    with pytest.raises(PermissionError):
        capture(data_root=tmp_path, as_of=dt.date(2026, 11, 6), output=out, probe_receipt=probe)
    retained = {str(p): p.read_bytes() for p in out.glob('clean_*/*')}
    monkeypatch.setattr(module, 'publish_directory', original)
    client = Client(lambda *a: (_ for _ in ()).throw(AssertionError('do not refetch old observation')))
    result = capture(data_root=tmp_path, as_of=dt.date(2026, 11, 6), output=out, connector=client)
    assert result['observed_at'] == '2026-11-06T10:00:00+00:00' and not client.calls
    assert all(Path(path).read_bytes() == data for path, data in retained.items())
    attempts = [json.loads(p.read_text()) for p in (out/'attempts').glob('*.json')]
    assert sorted(r['status'] for r in attempts) == ['captured', 'failed']
