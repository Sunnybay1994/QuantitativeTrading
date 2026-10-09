import datetime as dt
import json
import tomllib
from pathlib import Path

import polars as pl
import pytest

import quant.data.nightly_month_inputs as inputs


DAY = dt.date(2026, 8, 31)


def settings(tmp_path):
    refresh = tmp_path/'refresh.toml'
    refresh.write_text('stock_snapshot="fixture"\n')
    return {'data_root': str(tmp_path/'data'), 'execution_snapshot': 'old',
            'battery_config': 'battery.toml', 'refresh_config': str(refresh),
            'return_benchmark_config': 'returns.toml', 'measurement_config': 'measurement.toml'}


def test_price_delay_binds_prepared_index_and_preserves_original(tmp_path):
    spec = settings(tmp_path)
    original = Path(spec['refresh_config'])
    original.write_text('price_delay_index_version="old"\nstock_snapshot="fixture"\n')
    measure = tmp_path/'measure.toml'
    measure.write_text('index_version="prepared_official"\n')
    spec['measurement_config'] = str(measure)
    output = tmp_path/'run'
    output.mkdir()
    bound = inputs._bind_price_delay_index(spec, output)
    assert tomllib.loads(Path(bound['refresh_config']).read_text())['price_delay_index_version'] == 'prepared_official'
    assert tomllib.loads(original.read_text())['price_delay_index_version'] == 'old'
    assert inputs._bind_price_delay_index(bound, output) == bound


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
    monkeypatch.setattr(inputs, 'inspect_month_inputs', lambda **kw: {} if complete else
        ({'execution': 'old month', 'returns': 'old month'} if kw['settings']['execution_snapshot'] == 'old'
         else {'returns': 'old month'}))
    monkeypatch.setattr(inputs, 'refresh_stocks', lambda **kw: None)
    monkeypatch.setattr(inputs, 'refresh_industry', lambda **kw: None)
    monkeypatch.setattr(inputs, 'policy_of', lambda *a: 'legacy_daily_binary')
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
    assert seen == ['old']
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


@pytest.mark.parametrize('has_run_metadata', [False, True])
def test_return_extension_accepts_base_battery_and_preserves_original(monkeypatch, tmp_path, has_run_metadata):
    """Month rollover accepts both a base config and a prior run's config."""
    cutoff = dt.date(2026, 9, 30)
    old_cutoff = dt.date(2026, 8, 31)
    root = tmp_path / 'data'
    output = tmp_path / 'run'
    output.mkdir()
    members = root / 'clean/factor_benchmarks/old_members'
    members.mkdir(parents=True)
    pl.DataFrame({'snapshot_date': [dt.date(2026, 9, 1)], 'symbol': ['000001.SZ']}).write_parquet(members / 'members.parquet')
    battery = {'start': dt.date(2026, 1, 1), 'data': {
        'csi800_snapshot': 'old_members', 'limits_snapshot': 'old_limits'}}
    if has_run_metadata:
        battery['run'] = {'as_of': old_cutoff, 'retained_note': 'keep'}
    config = tmp_path / 'battery.toml'
    inputs._write_toml(config, battery)
    original = config.read_bytes()
    statistics = tmp_path / 'statistics'
    statistics.mkdir()
    inputs._write_toml(statistics / 'battery.toml', {'run': {'as_of': old_cutoff}})
    returns = tmp_path / 'returns.toml'
    inputs._write_toml(returns, {'benchmarks': {
        'equal_weight_snapshot': 'old_index', 'etf_total_return_snapshot': 'old_etf'}})
    # Completed synthetic downstream publications avoid network and full indexes.
    index = root / 'clean/equal_weight_indexes/new_month'
    index.mkdir(parents=True)
    (index / 'summary.json').write_text('{}')
    etf = root / 'clean/factor_benchmarks/new_month'
    etf.mkdir(parents=True)
    (etf / 'prices.parquet').write_bytes(b'completed fixture')
    calls = []
    def universe(**kwargs):
        calls.append(kwargs)
        return pl.DataFrame({'trade_date': [cutoff], 'symbol': ['000001.SZ']}), None
    monkeypatch.setattr(inputs, 'read_battery_year', universe)
    def unnecessary(**kwargs):
        pytest.fail('Existing publications must not trigger new collection or replay')
    for name in ('capture_csi800', 'publish', 'refresh_etfs', 'publish_etf_extension'):
        monkeypatch.setattr(inputs, name, unnecessary)
    result = inputs._extend_returns(dict(data_root=str(root), battery_config=str(config),
        return_benchmark_config=str(returns), statistics=[str(statistics)],
        reference_statistics=str(statistics), refresh_config='unused.toml'), cutoff, output, 'new_month')
    generated = tomllib.loads(Path(result['battery_config']).read_text())
    stats_config = tomllib.loads((output / 'benchmark_statistics/battery.toml').read_text())
    assert generated['run']['as_of'] == stats_config['run']['as_of'] == cutoff
    assert generated['start'] == battery['start']
    if has_run_metadata:
        assert generated['run']['retained_note'] == 'keep'
    assert config.read_bytes() == original
    assert len(calls) == 1 and calls[0]['known_through'] == cutoff
    assert calls[0]['start'] == battery['start'] and calls[0]['end'] == cutoff


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


@pytest.mark.parametrize('opening', [False, True])
def test_new_month_merges_new_dividend_and_master_without_touching_old(monkeypatch, tmp_path, opening):
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
        path.write_bytes(b'fixture raw')
        path.with_suffix('.json').write_text(json.dumps({'fetched_at': f'{DAY}T12:00:00+00:00',
            'checksum_sha256': inputs.digest(path)}))
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
    if opening:
        from quant.data.stock_open_suspensions import build_open_facts, POLICY
        keys = pl.read_parquet(old/'suspensions.parquet')
        empty = build_open_facts(keys, pl.DataFrame(), keys.with_columns(pl.lit(None, dtype=pl.Float64).alias('volume')))
        empty.write_parquet(old/'suspensions.parquet')
        empty.write_parquet(old/'suspension_open_facts.parquet')
        monkeypatch.setattr(inputs, 'read_stock_data', lambda **kw:
            pl.DataFrame({'symbol':['000001.SZ'],'trade_date':[DAY],'volume':[100.]}))
    result = inputs._daily_extensions(spec, DAY, tmp_path/'run', 'new')
    assert result['execution_snapshot'] == 'new'
    assert pl.read_parquet(old/'dividends.parquet').is_empty()
    assert pl.read_parquet(root/'clean/stock_execution/new/dividends.parquet')['div_cash'].to_list() == [.5]
    assert pl.read_parquet(root/'clean/stock_execution/new/instruments.parquet').height == 2
    assert pl.read_parquet(root/'clean/factor_execution/new/year=2026/limits.parquet').height == 2
    if opening:
        stops = pl.read_parquet(root/'clean/stock_execution/new/suspensions.parquet')
        assert stops.height == 2
        assert set(stops['suspension_policy']) == {POLICY}
        assert set(stops['open_status']) == {'unknown'}
        assert pl.read_parquet(old/'suspensions.parquet').is_empty()
