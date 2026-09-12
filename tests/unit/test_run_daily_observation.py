import datetime as dt
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from quant.research import run_daily_observation as daily


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


def test_missing_model_independent_accounts_continue(env):
    args, model, b20, b32, monthly = env
    model.return_value['status'] = 'missing_model_inputs'
    result = daily.run(**args)
    assert result['status'] == 'incomplete'
    assert b20.called and b32.called and monthly.called


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
