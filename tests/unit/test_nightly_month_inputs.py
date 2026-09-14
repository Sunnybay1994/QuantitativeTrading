import datetime as dt
import json
import tomllib

import polars as pl
import pytest

import quant.data.nightly_month_inputs as inputs


DAY = dt.date(2026, 8, 31)


def settings(tmp_path):
    return {'data_root': str(tmp_path/'data'), 'execution_snapshot': 'old',
            'battery_config': 'battery.toml', 'refresh_config': 'refresh.toml',
            'return_benchmark_config': 'returns.toml', 'measurement_config': 'measurement.toml'}


def test_covered_inputs_are_noop_without_network(monkeypatch, tmp_path):
    spec = settings(tmp_path)
    monkeypatch.setattr(inputs, 'latest_session', lambda **kw: DAY)
    monkeypatch.setattr(inputs, 'inspect_month_inputs', lambda **kw: {})
    monkeypatch.setattr(inputs, 'refresh_stocks', lambda **kw: pytest.fail('unnecessary network'))
    assert inputs.ensure_nightly_month_inputs(settings=spec, as_of=DAY, output=tmp_path/'run') == spec
    assert json.loads((tmp_path/'run/coverage.json').read_text())['network_required'] is False


def test_checkpoint_refuses_changed_month(monkeypatch, tmp_path):
    folder = tmp_path/'run'
    folder.mkdir()
    (folder/'request.json').write_text(json.dumps({'as_of': str(DAY)}))
    with pytest.raises(ValueError, match='another as_of'):
        inputs.ensure_nightly_month_inputs(settings=settings(tmp_path), as_of=dt.date(2026, 9, 30), output=folder)
    assert json.loads((folder/'request.json').read_text())['as_of'] == str(DAY)


def test_freshness_uses_oldest_mutable_request_not_snapshot_filename(tmp_path):
    source = tmp_path/'snapshot'
    source.mkdir()
    paths = []
    for api, timestamp in [('dividend', '2026-08-30T23:00:00+00:00'), ('stock_basic', '2026-09-01T10:00:00+00:00')]:
        path = tmp_path/f'raw/tushare/{api}/date=2026-09-01/response.parquet'
        path.parent.mkdir(parents=True)
        path.with_suffix('.json').write_text(json.dumps({'fetched_at': timestamp}))
        paths.append(str(path))
    (source/'sources.json').write_text(json.dumps(paths))
    assert inputs._mutable_capture_floor(source) == dt.date(2026, 8, 30)


def test_partial_clean_capture_is_retained_and_fresh_capture_requested(monkeypatch, tmp_path):
    folder = tmp_path/f'clean/stock_paper_inputs/date={DAY}'
    folder.mkdir(parents=True)
    (folder/'instruments.parquet').write_bytes(b'partial-clean')
    raw = tmp_path/'raw/original.parquet'
    raw.parent.mkdir()
    raw.write_bytes(b'original-raw')
    calls = []
    def capture(root, day):
        calls.append(day)
        assert not folder.exists()
        folder.mkdir()
        return folder
    monkeypatch.setattr(inputs, 'capture_stock_paper_day', capture)
    assert inputs._capture_day(tmp_path, DAY) == folder
    assert calls == [DAY]
    assert (folder.parent/f'.date={DAY}-attempt-1/instruments.parquet').read_bytes() == b'partial-clean'
    assert raw.read_bytes() == b'original-raw'


def test_failure_resumes_updated_execution_snapshot(monkeypatch, tmp_path):
    spec = settings(tmp_path)
    monkeypatch.setattr(inputs, 'latest_session', lambda **kw: DAY)
    complete = False
    monkeypatch.setattr(inputs, 'inspect_month_inputs', lambda **kw: {} if complete else {'returns': 'old month'})
    monkeypatch.setattr(inputs, 'refresh_stocks', lambda **kw: None)
    monkeypatch.setattr(inputs, 'refresh_industry', lambda **kw: None)
    seen = []
    def execution(s, *_):
        seen.append(s['execution_snapshot'])
        return {**s, 'execution_snapshot': 'new'}
    monkeypatch.setattr(inputs, '_daily_extensions', execution)
    def failure(*args):
        raise RuntimeError('interrupted benchmark')
    monkeypatch.setattr(inputs, '_extend_returns', failure)
    with pytest.raises(RuntimeError, match='interrupted'):
        inputs.ensure_nightly_month_inputs(settings=spec, as_of=DAY, output=tmp_path/'run')
    def finish(s, *_):
        nonlocal complete
        complete = True
        return s
    monkeypatch.setattr(inputs, '_extend_returns', finish)
    result = inputs.ensure_nightly_month_inputs(settings=spec, as_of=DAY, output=tmp_path/'run')
    assert seen == ['old', 'new']
    assert result['execution_snapshot'] == 'new'


def test_unresolved_session_gap_raises_instead_of_truncating(monkeypatch, tmp_path):
    monkeypatch.setattr(inputs, 'latest_session', lambda **kw: DAY)
    monkeypatch.setattr(inputs, 'inspect_month_inputs', lambda **kw: {'stocks': 'missing 2026-08-31'})
    monkeypatch.setattr(inputs, 'refresh_stocks', lambda **kw: None)
    with pytest.raises(ValueError, match='2026-08-31'):
        inputs.ensure_nightly_month_inputs(settings=settings(tmp_path), as_of=DAY, output=tmp_path/'run')
    assert not (tmp_path/'run/coverage.json').exists()


def test_new_publication_skips_interrupted_version(tmp_path):
    (tmp_path/'monthly').mkdir()
    (tmp_path/'monthly/data.parquet').write_bytes(b'partial')
    assert inputs._publication_version(tmp_path, 'monthly', 'summary.json') == 'monthly_attempt2'
    (tmp_path/'monthly_attempt2').mkdir()
    (tmp_path/'monthly_attempt2/summary.json').write_text('{}')
    assert inputs._publication_version(tmp_path, 'monthly', 'summary.json') == 'monthly_attempt2'
    assert (tmp_path/'monthly/data.parquet').read_bytes() == b'partial'


def test_configuration_roundtrip_preserves_cutoff_and_flags(tmp_path):
    spec = {'start': DAY, 'paths': ['some/path', 'another/path'], 'data': {'snapshot': 'new', 'enabled': False}, 'cost': 0.001}
    target = tmp_path/'config.toml'
    inputs._write_toml(target, spec)
    assert tomllib.loads(target.read_text()) == spec


def test_daily_extension_rejects_old_cached_mutable_facts(monkeypatch, tmp_path):
    root = tmp_path/'data'
    daily = root/f'clean/stock_paper_inputs/date={DAY}'
    daily.mkdir(parents=True)
    raw = root/'raw/tushare/stock_basic/date=2026-08-01/old.parquet'
    raw.parent.mkdir(parents=True)
    raw.with_suffix('.json').write_text(json.dumps({'fetched_at': '2026-08-01T12:00:00+00:00'}))
    (daily/'sources.json').write_text(json.dumps({'as_of': str(DAY), 'raw': [str(raw)]}))
    monkeypatch.setattr(inputs, '_execution_end', lambda *args: DAY-dt.timedelta(days=1))
    monkeypatch.setattr(inputs, 'available_sessions', lambda *args: [DAY])
    monkeypatch.setattr(inputs, '_capture_day', lambda *args: daily)
    with pytest.raises(ValueError, match='older request version'):
        inputs._daily_extensions(settings(tmp_path), DAY, tmp_path/'run', 'new')
    assert not (root/'clean/stock_execution/new').exists()


def test_new_month_merges_new_dividend_and_master_without_touching_old(monkeypatch, tmp_path):
    spec = settings(tmp_path)
    root = tmp_path/'data'
    old = root/'clean/stock_execution/old'
    daily = root/f'clean/stock_paper_inputs/date={DAY}'
    old.mkdir(parents=True)
    daily.mkdir(parents=True)
    old_day = dt.date(2026, 7, 31)
    old_bands = pl.DataFrame({'symbol': ['000001.SZ'], 'trade_date': [old_day], 'up_limit': [11.], 'down_limit': [9.]})
    old_bands.write_parquet(old/'limits.parquet')
    pl.DataFrame(schema={'symbol': pl.String, 'trade_date': pl.Date}).write_parquet(old/'suspensions.parquet')
    pl.DataFrame(schema={'symbol': pl.String, 'ex_date': pl.Date, 'div_cash': pl.Float64, 'adjust_share_price': pl.Boolean}).write_parquet(old/'dividends.parquet')
    pl.DataFrame({'symbol': ['000001.SZ']}).write_parquet(old/'instruments.parquet')
    old_bands.with_columns(pl.lit(DAY).alias('trade_date')).write_parquet(daily/'limits.parquet')
    pl.DataFrame(schema={'symbol': pl.String, 'trade_date': pl.Date}).write_parquet(daily/'suspensions.parquet')
    pl.DataFrame({'symbol': ['000001.SZ'], 'ex_date': [DAY], 'div_cash': [.5]}).write_parquet(daily/'dividends.parquet')
    pl.DataFrame({'symbol': ['000001.SZ', '000002.SZ']}).write_parquet(daily/'instruments.parquet')
    pl.DataFrame({'symbol': ['000001.SZ'], 'name': ['new-name']}).write_parquet(daily/'names.parquet')
    raw_paths = []
    for api in ('dividend', 'stock_basic'):
        path = root/f'raw/tushare/{api}/date={DAY}/fresh.parquet'
        path.parent.mkdir(parents=True)
        path.with_suffix('.json').write_text(json.dumps({'fetched_at': f'{DAY}T12:00:00+00:00'}))
        raw_paths.append(str(path))
    (daily/'sources.json').write_text(json.dumps({'as_of': str(DAY), 'raw': raw_paths}))
    limits = root/'clean/factor_execution/old/year=2026'
    limits.mkdir(parents=True)
    old_bands.write_parquet(limits/'limits.parquet')
    (root/'clean/stock_name_history').mkdir()
    battery = tmp_path/'battery.toml'
    inputs._write_toml(battery, {'start': dt.date(2026, 8, 1), 'data': {'limits_snapshot': 'old'}})
    spec['battery_config'] = str(battery)
    monkeypatch.setattr(inputs, '_execution_end', lambda *args: old_day)
    monkeypatch.setattr(inputs, 'available_sessions', lambda *args: [old_day, DAY])
    monkeypatch.setattr(inputs, '_capture_day', lambda *args: daily)
    monkeypatch.setattr(inputs.CleanInstrumentStore, 'upsert', lambda *args: 2)
    result = inputs._daily_extensions(spec, DAY, tmp_path/'run', 'new')
    assert result['execution_snapshot'] == 'new'
    assert pl.read_parquet(old/'dividends.parquet').is_empty()
    assert pl.read_parquet(root/'clean/stock_execution/new/dividends.parquet')['div_cash'].to_list() == [.5]
    assert pl.read_parquet(root/'clean/stock_execution/new/instruments.parquet').height == 2
    assert pl.read_parquet(root/'clean/factor_execution/new/year=2026/limits.parquet').height == 2
