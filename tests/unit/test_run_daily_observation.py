import datetime as dt
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from quant.research import run_daily_observation as daily


@pytest.mark.parametrize('failures', [2, 6])
def test_report_replace_handles_transient_conflict_but_surfaces_persistent_error(tmp_path, monkeypatch, failures):
    target, temporary = tmp_path/'summary.json', tmp_path/'summary.json.tmp'
    target.write_text('old')
    temporary.write_text('new')
    replace = Path.replace
    calls = []

    def competing_reader(path, destination):
        calls.append(path)
        if len(calls) <= failures:
            raise PermissionError('Reader holds the destination')
        return replace(path, destination)

    monkeypatch.setattr(Path, 'replace', competing_reader)
    monkeypatch.setattr(daily.time, 'sleep', lambda _: None)
    if failures == 6:
        with pytest.raises(PermissionError):
            daily._replace_report(temporary, target)
        assert target.read_text() == 'old' and temporary.read_text() == 'new'
        assert len(calls) == 6
    else:
        daily._replace_report(temporary, target)
        assert target.read_text() == 'new' and not temporary.exists()
        assert len(calls) == 3


@pytest.fixture
def env(tmp_path, monkeypatch):
    config = tmp_path/'config.toml'
    text = Path('configs/research/daily_observation_v1.toml').read_text(encoding='utf-8-sig')
    config.write_text(text, encoding='utf-8')
    monkeypatch.setattr(daily, 'latest_session', Mock(return_value=dt.date(2026, 9, 11)))
    model = Mock(return_value={'as_of': '2026-09-11', 'status': 'recorded'})
    def saved_model(**kwargs):
        kwargs['output'].mkdir()
        (kwargs['output']/'refresh.json').write_text(json.dumps({
            'latest_session': '2026-09-11', 'intraday_errors': [], 'input_quality': {'errors': []}}))
        return model.return_value
    model.side_effect = saved_model
    b20 = Mock(return_value={'as_of': '2026-09-11', 'accounts': [
        {'output': f'/account/{i}/2026-09-11'} for i in range(6)]})
    b32 = Mock(return_value={'accounts': [
        {'account': a, 'as_of': '2026-09-11'} for a in daily.ACCOUNTS]})
    monthly = Mock(return_value={'as_of': '2026-09-11'})
    for name, mock in [('run_daily', model), ('run_b20', b20),
                       ('run_b32', b32), ('run_monthly', monthly)]:
        monkeypatch.setattr(daily, name, mock)
    monkeypatch.setattr(daily, 'run_risk', Mock(return_value={'status': 'complete'}))
    root = tmp_path/'accounts'
    for account in daily.ACCOUNTS:
        folder = root/'b32'/account/'2026-09-11'
        folder.mkdir(parents=True)
        (folder/'state.json').write_text('{}')
    args = dict(config=config, output=tmp_path/'record', to='2026-09-11',
                saved_data=True, rehearsal=True, account_root=root)
    return args, model, b20, b32, monthly


def test_saved_isolated_and_controls_not_overridden(env):
    args, model, b20, b32, monthly = env
    result = daily.run(**args)
    assert result['status'] == 'complete'
    assert b20.call_args.kwargs['refresh_data'] is False
    assert b32.call_args.kwargs['output'] == args['account_root']/'b32'
    assert 'halt' not in b32.call_args.kwargs and 'sell_only' not in b32.call_args.kwargs
    assert model.call_args.kwargs['rehearsal'] is True
    assert monthly.call_count == 1


def test_q10_monthly_runs_independently_of_b32_monthly_failure(env, monkeypatch):
    from quant.execution import q10_paper
    from quant.reporting import q10_monthly
    args, *_ = env
    with args['config'].open('a', encoding='utf-8') as stream:
        stream.write('\n[q10]\nconfig="fixture"\noutput="fixture"\nmonthly_backtest="frozen"\n')
    args['rehearsal'] = False
    monkeypatch.setattr(daily, 'latest_session', lambda **k: dt.date(2026, 9, 14))
    monkeypatch.setattr(q10_paper, 'run', Mock(return_value={'as_of': '2026-09-14'}))
    monthly = Mock(return_value={'status': 'recorded'})
    monkeypatch.setattr(q10_monthly, 'run', monthly)
    result = daily.run(**args)
    assert result['stages']['q10_monthly']['status'] == 'complete'
    assert monthly.call_args.kwargs['as_of'] == dt.date(2026, 9, 14)
    assert monthly.call_args.kwargs['backtest'] == Path('frozen')


@pytest.mark.parametrize('errors', [[], [{'input': 'minute', 'error': 'missing'}]])
def test_tracking_uses_isolated_accounts_and_surfaces_input_errors(env, monkeypatch, errors):
    from quant.execution import shadow_slippage
    from quant.reporting import forward_dashboard
    args, *_ = env
    with args['config'].open('a', encoding='utf-8') as stream:
        stream.write('\n[forward_tracking]\nenabled = true\ntdx_recovery_root = "local_tdx"\n')
    shadow = Mock(return_value={'errors': errors, 'requires_review': bool(errors)})
    view = Mock(return_value={'status': 'complete'})
    monkeypatch.setattr(shadow_slippage, 'run', shadow)
    monkeypatch.setattr(forward_dashboard, 'run', view)
    result = daily.run(**args)
    specs = shadow.call_args.kwargs['accounts']
    assert len(specs) == 8
    assert all(args['account_root'] in Path(spec['root']).parents for spec in specs)
    assert shadow.call_args.kwargs['known_through'] == dt.date(2026, 9, 11)
    assert shadow.call_args.kwargs['tdx_recovery_root'] == Path('local_tdx')
    assert view.call_args.kwargs['output'] == args['output']/'forward_tracking'
    assert result['stages']['forward_tracking']['status'] == ('incomplete' if errors else 'complete')


def test_missing_model_independent_accounts_continue(env):
    args, model, b20, b32, monthly = env
    model.return_value['status'] = 'missing_model_inputs'
    result = daily.run(**args)
    assert result['status'] == 'incomplete'
    assert b20.called and b32.called and monthly.called


def test_stage_duration_recorded_for_failure_and_success(env, monkeypatch):
    args, model, _, _, _ = env
    ticks = iter(range(100))
    monkeypatch.setattr(daily.time, 'monotonic', lambda: next(ticks))
    model.side_effect = ValueError('temporary input failure')
    result = daily.run(**args)
    assert result['stages']['model']['elapsed_seconds'] == 1
    assert result['stages']['b20']['elapsed_seconds'] == 1
    report = (args['output']/'report.md').read_text(encoding='utf-8')
    assert '耗时（秒）' in report and '|失败|1.0|' in report


def test_live_refresh_failure_blocks_stock_only(env):
    args, model, b20, b32, monthly = env
    args['saved_data'] = False
    model.side_effect = ValueError('provider missing')
    result = daily.run(**args)
    assert result['status'] == 'incomplete'
    assert b20.call_args.kwargs['refresh_data'] is True
    assert not b32.called and not monthly.called


def test_live_refresh_good_model_failure_still_advances_stock(env):
    args, model, _, b32, _ = env
    args['saved_data'] = False
    def failed_model(**kwargs):
        kwargs['output'].mkdir()
        (kwargs['output']/'refresh.json').write_text(json.dumps({
            'latest_session': '2026-09-11', 'intraday_errors': [], 'input_quality': {'errors': []}}))
        raise ValueError('model inputs missing')
    model.side_effect = failed_model
    result = daily.run(**args)
    assert b32.called and result['status'] == 'incomplete'


@pytest.mark.parametrize('component', ['b20', 'b32', 'monthly'])
def test_stale_date_is_incomplete(env, component):
    args, _, b20, b32, monthly = env
    if component == 'b20':
        b20.return_value['as_of'] = '2026-09-10'
    elif component == 'b32':
        b32.return_value['accounts'][0]['as_of'] = '2026-09-10'
    else:
        monthly.return_value['as_of'] = '2026-09-10'
    result = daily.run(**args)
    assert result['stages'][component]['status'] == 'incomplete'
    assert result['status'] == 'incomplete'


def test_b20_exception_stock_continues(env):
    args, _, b20, b32, _ = env
    b20.side_effect = FileNotFoundError('ETF snapshot')
    result = daily.run(**args)
    assert b32.called and result['stages']['b20']['status'] == 'failed'


def test_monthly_future_snapshots_blocked(env):
    args, _, _, _, monthly = env
    folder = args['account_root']/'b32'/daily.ACCOUNTS[0]/'2026-09-14'
    folder.mkdir()
    (folder/'state.json').write_text('{}')
    assert daily.run(**args)['stages']['monthly']['status'] == 'failed'
    assert not monthly.called


@pytest.mark.parametrize('change', ['no_root', 'production', 'outside', 'same'])
def test_unsafe_rehearsal_rejected_before_calls(env, change):
    args, model, _, _, _ = env
    if change == 'no_root':
        args['account_root'] = None
    elif change == 'production':
        args['b20_output'] = Path('artifacts/forward/b20')
    elif change == 'outside':
        args['b20_output'] = args['output'].parent/'outside'
    else:
        args['b20_output'] = args['account_root']/'b32'
    with pytest.raises(ValueError):
        daily.run(**args)
    assert not model.called


def test_calendar_failure_saved_summary(env, monkeypatch):
    args, model, _, _, _ = env
    monkeypatch.setattr(daily, 'latest_session', Mock(side_effect=ValueError('calendar missing')))
    result = daily.run(**args)
    assert result['status'] == 'incomplete' and not model.called
    assert (args['output']/'summary.json').is_file()


def test_cli_nonzero(env, monkeypatch):
    args, *_ = env
    monkeypatch.setattr(daily, 'run', Mock(return_value={'status': 'incomplete'}))
    monkeypatch.setattr('sys.argv', ['daily', '--output', str(args['output'])])
    with pytest.raises(SystemExit, match='1'):
        daily.main()


def test_risk_failure_propagates_without_repeating_accounts(env, monkeypatch):
    args, _, b20, b32, _ = env
    risk = Mock(return_value={'status': 'incomplete'})
    monkeypatch.setattr(daily, 'run_risk', risk)
    result = daily.run(**args)
    assert result['status'] == 'incomplete'
    assert result['stages']['risk']['status'] == 'incomplete'
    assert b20.call_count == b32.call_count == risk.call_count == 1
    assert risk.call_args.kwargs['output'] == args['output']/'risk'
    with pytest.raises(FileExistsError):
        daily.run(**args)
    assert b20.call_count == b32.call_count == 1


def test_interrupt_preserves_completed_stage_and_running_marker(env):
    args, _, b20, b32, _ = env
    b20.side_effect = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        daily.run(**args)
    saved = json.loads((args['output']/'summary.json').read_text(encoding='utf-8'))
    assert saved['status'] == 'incomplete'
    assert saved['stages']['model']['status'] == 'complete'
    assert saved['stages']['b20']['status'] == 'running'
    assert not b32.called


def test_monitor_insufficient_is_visible_and_failure_is_incomplete(env, monkeypatch):
    args, *_ = env
    monitor = Mock(return_value={'status': 'insufficient', 'requires_review': False})
    monkeypatch.setattr(daily, 'run_monitor', monitor)
    result = daily.run(**args)
    assert result['status'] == 'complete'
    assert result['signal_monitor_status'] == 'insufficient'
    assert monitor.call_args.kwargs['known_through'] == dt.date(2026, 9, 11)
    args['output'] = args['output'].with_name('record_monitor_failure')
    monitor.side_effect = ValueError('missing labels')
    result = daily.run(**args)
    assert result['status'] == 'incomplete' and result['requires_review']


def test_saved_quality_failure_propagates_and_accounts_validate_independently(env):
    args, model, b20, b32, monthly = env
    errors = ['pit_sue8: incompatible PIT report context', 'other saved value mismatch']
    def failed_quality(**kwargs):
        kwargs['output'].mkdir()
        (kwargs['output']/'refresh.json').write_text(json.dumps({
            'latest_session': '2026-09-11', 'intraday_errors': [], 'input_quality': {'errors': errors}}))
        return {'as_of': '2026-09-11', 'status': 'input_errors', 'input_errors': errors}
    model.side_effect = failed_quality
    result = daily.run(**args)
    assert result['status'] == 'incomplete'
    assert result['stages']['model']['status'] == 'incomplete'
    assert result['stages']['refresh']['status'] == 'failed'
    assert result['stages']['refresh']['input_errors'] == errors
    assert b20.called and b32.called and monthly.called
    assert result['signal_monitor_status'] == 'insufficient'


@pytest.mark.parametrize('health_status', ['recorded', 'unavailable'])
def test_health_summary_survives_blocked_model_and_independent_accounts(env, health_status):
    args, model, b20, b32, monthly = env
    health = {'enabled': True, 'status': health_status, 'as_of': '2026-09-11',
        'output': 'model/input_quality/factor_health', 'diagnostics_only': True}
    error = 'pit_sue8: incompatible PIT context'
    def checked(**kwargs):
        kwargs['output'].mkdir()
        (kwargs['output']/'refresh.json').write_text(json.dumps({
            'latest_session': '2026-09-11', 'intraday_errors': [],
            'input_quality': {'errors': [error], 'factor_health': health}}))
        return {'as_of': '2026-09-11', 'status': 'input_errors', 'input_errors': [error],
                'factor_health': health}
    model.side_effect = checked
    result = daily.run(**args)
    assert result['factor_health'] == health
    assert result['stages']['refresh']['input_errors'] == [error]
    assert result['status'] == 'incomplete'
    assert model.call_count == b20.call_count == b32.call_count == monthly.call_count == 1
    assert json.loads((args['output']/'summary.json').read_text(encoding='utf-8'))['factor_health'] == health
    report = (args['output']/'report.md').read_text(encoding='utf-8')
    assert '历史演练' in report and '本次模型预测：0只股票' in report
    assert error in report and '|B20六账户|完成|' in report and '|B32双账户|完成|' in report
    assert '因子健康日志' in report


@pytest.mark.parametrize('status', ['pending', 'no_forecasts', 'failed'])
def test_configured_forecast_scoring_continuation(env, monkeypatch, status):
    from quant.reporting import daily_forecast_monitor
    import tomllib
    args, _, b20, b32, _ = env
    content = args['config'].read_text(encoding='utf-8')
    selection = tomllib.loads(content)['model']['selection']
    args['config'].write_text(content+'\n[forecast_monitor]\nselection='+json.dumps(selection)+'\n')
    operation = Mock(return_value={'status': status, 'requires_review': status == 'failed'})
    monkeypatch.setattr(daily_forecast_monitor, 'run', operation)
    result = daily.run(**args)
    assert operation.call_args.kwargs['current'] == args['output']/'model/forecast'
    assert result['signal_monitor_status'] == status
    assert result['stages']['signal_monitor']['status'] == ('complete' if status == 'pending' else 'incomplete')
    assert b20.called and b32.called
