"""Independent checks at the consumer-scope and daily/minute workflow boundary."""
import datetime as dt
import json
import tomllib
from pathlib import Path
from unittest.mock import Mock

import pytest

from quant.data import daily_input_quality, refresh, refresh_minute_factors
from quant.factors import compute
from quant.research import daily_dependencies, run_daily_model_forecast, run_daily_observation


DAY = dt.date(2026, 9, 29)
CLOCK = dt.datetime(2026, 9, 29, 23, tzinfo=refresh.SHANGHAI)


def input_config(tmp_path):
    library = tmp_path/'library'
    library.mkdir()
    for name, expression in [('model_factor', 'adj_close'), ('candidate_factor', 'volume'),
                             ('research_minute', 'ts_mean(minute_smart_vwap, 20)')]:
        (library/f'{name}.toml').write_text(f'id="{name}"\nexpr="{expression}"\n'
            'direction=1\nfamily="fixture"\nsource_ref="fixture"\n')
    etf = tmp_path/'etf.toml'
    etf.write_text('[universe]\nsymbols=["510300.SH"]\n')
    battery = tmp_path/'battery.toml'
    battery.write_text('minimum_symbols=100\n')
    config = tmp_path/'refresh.toml'
    config.write_text(f'etf_config="{etf.as_posix()}"\nfinancial_snapshot="old_financial"\n'
        'factor_benchmark_snapshot="old_benchmark"\n[intraday]\nstock_lookback_days=7\n'
        f'[factors]\nenabled=true\nlibrary="{library.as_posix()}"\nselected="all"\nstart="2010-01-01"\n'
        '[financials]\nenabled=true\nlookback_days=3\n'
        f'[quality]\nenabled=true\nbattery_config="{battery.as_posix()}"\n')
    return config


def providers(monkeypatch):
    monkeypatch.setattr(refresh, 'latest_session', lambda **kw: DAY)
    monkeypatch.setattr(refresh, 'refresh_stocks', lambda **kw: {'new_dates': [], 'new_rows': 0})
    monkeypatch.setattr(refresh, 'refresh_etfs', lambda **kw: {'new_rows': 0, 'new_bar_rows': 0})
    monkeypatch.setattr(refresh, 'refresh_limits', lambda **kw: 0)
    monkeypatch.setattr(refresh, 'refresh_stock_limits', lambda **kw: {'new_rows': 0})


def test_scope_reaches_compute_and_quality_without_forking_snapshot_updates(tmp_path, monkeypatch):
    config = input_config(tmp_path)
    providers(monkeypatch)
    def financial(**kwargs):
        assert kwargs['config'] == config
        config.write_text(config.read_text().replace('old_financial', 'new_financial'))
        return {'new_rows': 1, 'financial_snapshot': 'new_financial'}
    def benchmark(**kwargs):
        assert kwargs['config'] == config
        config.write_text(config.read_text().replace('old_benchmark', 'new_benchmark'))
        return {'new_rows': 1, 'snapshot': 'new_benchmark'}
    required = ['candidate_factor', 'model_factor']
    computed, checked = [], []
    def calculation(**kwargs):
        spec = tomllib.loads(kwargs['refresh_config'].read_text())
        assert spec['financial_snapshot'] == 'new_financial'
        assert spec['factor_benchmark_snapshot'] == 'new_benchmark'
        computed.extend(kwargs['selected'].split(','))
        return {'years': [], 'factor_count': 2, 'output': 'fixture'}
    def quality(**kwargs):
        assert kwargs['config'] == config
        assert kwargs['financials']['financial_snapshot'] == 'new_financial'
        checked.extend(row['id'] for row in kwargs['factors'])
        return {'errors': []}
    minutes = Mock(side_effect=AssertionError('Unneeded minute provider called'))
    monkeypatch.setattr(refresh, 'refresh_disclosed_financials', financial)
    monkeypatch.setattr(refresh, 'refresh_factor_benchmark', benchmark)
    monkeypatch.setattr(refresh, 'refresh_intraday', minutes)
    monkeypatch.setattr(compute, 'run', calculation)
    monkeypatch.setattr(daily_input_quality, 'run_quality', quality)
    result = refresh.run_refresh(to=str(DAY), data_root=tmp_path, artifact_root=tmp_path,
        config=config, now=CLOCK, intraday=False, required_factor_ids=required)
    assert computed == required and sorted(checked) == sorted(required)
    assert result['required_factor_ids'] == required and result['intraday_requested'] is False
    assert tomllib.loads(config.read_text())['factors']['selected'] == 'all'
    assert tomllib.loads(config.read_text())['financial_snapshot'] == 'new_financial'
    assert not minutes.called


def test_saved_quality_uses_identical_factor_scope(tmp_path, monkeypatch):
    config = input_config(tmp_path)
    seen = []
    def quality(**kwargs):
        seen.extend(row['id'] for row in kwargs['factors'])
        return {'errors': []}
    monkeypatch.setattr(run_daily_model_forecast, 'run_quality', quality)
    result = run_daily_model_forecast.check_saved_input_quality(data_root=tmp_path,
        config=config, end=DAY, output=tmp_path/'quality',
        required_factor_ids=['model_factor', 'candidate_factor'])
    assert result['errors'] == [] and sorted(seen) == ['candidate_factor', 'model_factor']


@pytest.mark.parametrize('saved', [False, True])
def test_scope_omitting_required_model_factor_cannot_refresh_or_forecast(tmp_path, monkeypatch, saved):
    config = input_config(tmp_path)
    selection = tmp_path/'selection'
    selection.mkdir()
    (selection/'selection.json').write_text(json.dumps({'conclusion': 'RESEARCH_ONLY',
        'auto_trade': False, 'forward_start': '2026-09-14'}))
    monkeypatch.setattr(run_daily_model_forecast, 'latest_session', lambda **kw: DAY)
    monkeypatch.setattr(run_daily_model_forecast, 'model_factor_requirements', lambda **kw: {
        'required_factors': ['model_factor'], 'required_outside_refresh_selection': [], 'required_excluded': []})
    provider = Mock(side_effect=AssertionError('Bad scope must not refresh'))
    saved_check = Mock(side_effect=AssertionError('Bad scope must not read saved quality'))
    forecast = Mock(side_effect=AssertionError('Bad scope must not forecast'))
    monkeypatch.setattr(run_daily_model_forecast, 'run_refresh', provider)
    monkeypatch.setattr(run_daily_model_forecast, 'check_saved_input_quality', saved_check)
    monkeypatch.setattr(run_daily_model_forecast, 'run_forecast', forecast)
    result = run_daily_model_forecast.run_daily(to=str(DAY), selection=selection,
        output=tmp_path/'record', data_root=tmp_path, artifact_root=tmp_path, refresh_config=config,
        now=CLOCK, saved_data=saved, required_factor_ids=['candidate_factor'])
    assert result['status'] == 'input_errors'
    assert any('omits model factors' in error for error in result['input_errors'])
    assert not provider.called and not saved_check.called and not forecast.called


def observation_fixture(tmp_path, monkeypatch):
    config = tmp_path/'daily.toml'
    config.write_text('auto_trade=false\ndependency_refresh=true\nintraday=true\n'
        f'data_root="{tmp_path.as_posix()}"\nartifact_root="{tmp_path.as_posix()}"\n'
        'refresh_config="unused"\n[model]\nselection="unused"\n'
        f'[b20]\nconfig="unused"\noutput="{(tmp_path/"accounts/b20").as_posix()}"\n'
        f'[b32]\nconfig="unused"\noutput="{(tmp_path/"accounts/b32").as_posix()}"\n'
        '[forward_tracking]\nenabled=true\n')
    monkeypatch.setattr(run_daily_observation, 'latest_session', lambda **kw: DAY)
    model = Mock()
    def forecast(**kwargs):
        kwargs['output'].mkdir()
        (kwargs['output']/'refresh.json').write_text(json.dumps({'latest_session': str(DAY),
            'intraday_errors': [], 'input_quality': {'errors': []}}))
        return {'status': 'recorded', 'as_of': str(DAY)}
    model.side_effect = forecast
    b32 = Mock(return_value={'accounts': [{'account': name, 'as_of': str(DAY)}
                                         for name in run_daily_observation.ACCOUNTS]})
    monkeypatch.setattr(run_daily_observation, 'run_daily', model)
    monkeypatch.setattr(run_daily_observation, 'run_b32', b32)
    monkeypatch.setattr(run_daily_observation, 'run_b20', lambda **kw: {'as_of': str(DAY),
        'accounts': [{'output': f'account/{i}/{DAY}'} for i in range(6)]})
    monkeypatch.setattr(run_daily_observation, 'run_risk', lambda **kw: {'status': 'complete', 'requires_review': False})
    monkeypatch.setattr(run_daily_observation, 'run_monitor', lambda **kw: {'status': 'pending', 'requires_review': False})
    monkeypatch.setattr(run_daily_observation, 'run_monthly', lambda **kw: {'as_of': str(DAY)})
    from quant.execution import b16_forward, shadow_slippage
    from quant.reporting import forward_dashboard
    monkeypatch.setattr(b16_forward, 'daily', lambda **kw: {'status': 'pending_first_signal'})
    monkeypatch.setattr(shadow_slippage, 'run', lambda **kw: {'errors': [], 'requires_review': False})
    monkeypatch.setattr(forward_dashboard, 'run', lambda **kw: {'status': 'complete'})
    for name in run_daily_observation.ACCOUNTS:
        folder = tmp_path/'accounts/b32'/name/str(DAY)
        folder.mkdir(parents=True)
        (folder/'state.json').write_text('{}')
    return config, model, b32


@pytest.mark.parametrize('minute_inputs', [[], ['minute_smart_vwap']])
def test_daily_passes_resolved_scope_and_preserves_real_minute_dependencies(tmp_path, monkeypatch, minute_inputs):
    config, model, b32 = observation_fixture(tmp_path, monkeypatch)
    plan = {'required_factor_ids': ['model_factor', 'candidate_factor'], 'required_minute_inputs': minute_inputs}
    monkeypatch.setattr(daily_dependencies, 'resolve_daily_dependencies', lambda **kw: plan)
    result = run_daily_observation.run(config=config, output=tmp_path/'record', to=str(DAY), now=CLOCK)
    assert model.call_args.kwargs['required_factor_ids'] == plan['required_factor_ids']
    assert model.call_args.kwargs['intraday'] is bool(minute_inputs)
    assert result['status'] == 'complete' and b32.called
    assert json.loads((tmp_path/'record/dependencies.json').read_text()) == plan


def test_dependency_failure_does_not_advance_production_b32_or_claim_complete(tmp_path, monkeypatch):
    config, model, b32 = observation_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(daily_dependencies, 'resolve_daily_dependencies', Mock(side_effect=ValueError('changed freeze')))
    result = run_daily_observation.run(config=config, output=tmp_path/'record', to=str(DAY), now=CLOCK)
    assert not model.called and not b32.called
    assert result['stages']['dependencies']['status'] == 'failed'
    assert result['stages']['refresh']['status'] == 'failed'
    assert result['status'] == 'incomplete'


def test_removed_collection_does_not_hide_missing_shadow_minutes(tmp_path, monkeypatch):
    config, model, b32 = observation_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(daily_dependencies, 'resolve_daily_dependencies', lambda **kw: {
        'required_factor_ids': ['model_factor'], 'required_minute_inputs': []})
    from quant.execution import shadow_slippage
    monkeypatch.setattr(shadow_slippage, 'run', lambda **kw: {'errors': [{'error': 'missing order minute window'}],
        'requires_review': True, 'missing_horizons': 3})
    result = run_daily_observation.run(config=config, output=tmp_path/'record', to=str(DAY), now=CLOCK)
    assert model.call_args.kwargs['intraday'] is False and b32.called
    assert result['stages']['forward_tracking']['status'] == 'incomplete'
    assert result['status'] == 'incomplete' and result['requires_review'] is True


def test_minute_maintenance_is_bounded_and_retains_partial_receipt(tmp_path, monkeypatch):
    config = input_config(tmp_path)
    monkeypatch.setattr(refresh_minute_factors, 'latest_session', lambda **kw: DAY)
    from quant.data import intraday
    monkeypatch.setattr(intraday, 'refresh_intraday', lambda **kw: {'errors': ['source paused'],
        'stock_changed_rows': 5, 'deferred_stock_symbols': ['000001.SZ']})
    calls = []
    def calculation(**kwargs):
        calls.append(kwargs)
        return {'years': [], 'factor_count': 1, 'output': 'fixture'}
    monkeypatch.setattr(compute, 'run', calculation)
    result = refresh_minute_factors.run(config=config, data_root=tmp_path, artifact_root=tmp_path,
        output=tmp_path/'record', to=str(DAY), collect=True, now=CLOCK)
    assert result['status'] == 'partial' and result['minutes']['errors'] == ['source paused']
    assert result['minutes']['deferred_stock_symbols'] == ['000001.SZ']
    assert result['rebuild_start'] == '2026-09-23'
    assert calls and all(call['selected'] == 'research_minute' for call in calls)
    assert all(call['start'] >= dt.date(2026, 9, 23) for call in calls)
