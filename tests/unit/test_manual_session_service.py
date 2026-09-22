"""Offline service safety, durable demo and exported NAV integration."""
import datetime as dt
import json
from pathlib import Path
import socket

import polars as pl
import pytest

from quant.data.stock_paper_inputs import DIVIDEND_SCHEMA
from quant.execution.manual_nav import close_manual_day
from quant.execution.manual_session import ManualSession
from quant.execution.manual_session_cli import demo
from quant.execution.manual_session_service import instance_lock, load_settings, serve


CONFIG = '''broker = "银河证券"
planned_capital = 100000
mode = "rehearsal"
auto_trade = false
live_notifications = false
enabled = false
sender_id = "demo_user"
chat_id = "demo_chat"
'''


def write_config(tmp_path, source=CONFIG):
    path = tmp_path / 'manual.toml'
    path.write_text(source, encoding='utf-8')
    return path


@pytest.fixture
def prohibit_network(monkeypatch):
    from quant.notify import feishu_manual

    def forbidden(*args, **kwargs):
        pytest.fail('Offline acceptance must not construct transport or touch network')

    monkeypatch.setattr(feishu_manual, 'FeishuManualTransport', forbidden)
    monkeypatch.setattr(feishu_manual, 'run_long_connection', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)


def test_repository_settings_default_to_disabled_rehearsal():
    path = Path(__file__).resolve().parents[2] / 'configs/trading/manual_galaxy_100k.toml'
    config = load_settings(path)
    assert config['broker'] == '银河证券'
    assert config['planned_capital'] == 100000
    assert config['mode'] == 'rehearsal'
    assert config['auto_trade'] is False
    assert config['live_notifications'] is False
    assert config['enabled'] is False
    assert config['sender_id'] == config['chat_id'] == ''


@pytest.mark.parametrize(('before', 'after'), [
    ('mode = "rehearsal"', 'mode = "live"'),
    ('auto_trade = false', 'auto_trade = true'),
    ('auto_trade = false', 'auto_trade = "false"'),
    ('auto_trade = false\n', ''),
    ('live_notifications = false', 'live_notifications = true'),
    ('live_notifications = false\n', ''),
    ('broker = "银河证券"', 'broker = "other"'),
    ('planned_capital = 100000', 'planned_capital = 1000000'),
])
def test_unsafe_profiles_rejected(tmp_path, before, after):
    with pytest.raises(ValueError):
        load_settings(write_config(tmp_path, CONFIG.replace(before, after)))


@pytest.mark.parametrize(('enabled', 'explicit'), [(False, False), (False, True), (True, False)])
def test_serve_requires_both_opt_ins_before_any_network(tmp_path, prohibit_network, enabled, explicit):
    config = write_config(tmp_path, CONFIG.replace('enabled = false', f'enabled = {str(enabled).lower()}'))
    database = tmp_path / 'not-created.sqlite'
    with pytest.raises(ValueError, match='disabled'):
        serve(database, config, send_rehearsal=explicit)
    assert not database.exists()


def test_missing_enabled_is_disabled(tmp_path, prohibit_network):
    config = write_config(tmp_path, CONFIG.replace('enabled = false\n', ''))
    with pytest.raises(ValueError, match='disabled'):
        serve(tmp_path / 'session.sqlite', config, send_rehearsal=True)


@pytest.mark.parametrize('value', ['"false"', '"true"', '1', '0'])
def test_enabled_requires_actual_boolean_not_truthy_text_or_integer(tmp_path, value):
    config = write_config(tmp_path, CONFIG.replace('enabled = false', f'enabled = {value}'))
    with pytest.raises(ValueError):
        load_settings(config)


def test_enabled_requires_initialized_database_before_network(tmp_path, prohibit_network):
    config = write_config(tmp_path, CONFIG.replace('enabled = false', 'enabled = true'))
    with pytest.raises(ValueError, match='Initialize'):
        serve(tmp_path / 'missing.sqlite', config, send_rehearsal=True)


def test_enabled_requires_credentials_before_network(tmp_path, monkeypatch, prohibit_network):
    from quant.notify import feishu_credentials
    monkeypatch.setattr(feishu_credentials, 'load_local', lambda: None)
    folder = tmp_path / 'demo'
    demo(folder)
    config = write_config(tmp_path, CONFIG.replace('enabled = false', 'enabled = true'))
    monkeypatch.delenv('FEISHU_APP_ID', raising=False)
    monkeypatch.delenv('FEISHU_APP_SECRET', raising=False)
    with pytest.raises(ValueError, match='FEISHU_APP_ID'):
        serve(folder / 'session.sqlite', config, send_rehearsal=True)


def test_instance_lock_excludes_second_owner_and_releases(tmp_path):
    path = tmp_path / 'manual.lock'
    with instance_lock(path):
        with pytest.raises(OSError):
            with instance_lock(path):
                pytest.fail('Second owner acquired lock')
    assert path.exists()
    with instance_lock(path):
        pass


def test_instance_lock_releases_after_exception(tmp_path):
    path = tmp_path / 'manual.lock'
    with pytest.raises(RuntimeError, match='worker failed'):
        with instance_lock(path):
            raise RuntimeError('worker failed')
    with instance_lock(path):
        pass


def test_demo_export_equals_reopened_durable_session(tmp_path, prohibit_network):
    folder = tmp_path / 'demo'
    result = demo(folder)
    assert result == {'output': str(folder), 'cash': 89489., 'shares': 1000,
                      'network_used': False, 'auto_trade': False, 'mode': 'rehearsal'}
    expected = json.loads((folder / 'report/summary.json').read_text(encoding='utf-8'))
    reopened = ManualSession(folder / 'session.sqlite')
    try:
        assert reopened.snapshot() == expected
        assert len(reopened.events()) == 2
        assert expected['book']['holdings'] == {'600000.SH': {'quantity': 1000, 'mark_price': 10.51}}
        assert expected['fee_pending_fills'] == 0
        assert expected['cash_and_nav_final'] is False
        assert '000001.SZ' not in expected['book']['holdings']
    finally:
        reopened.close()
    with pytest.raises(FileExistsError):
        demo(folder)


def test_exported_actual_fills_close_nav_with_synthetic_price(tmp_path, prohibit_network):
    folder = tmp_path / 'demo'
    demo(folder)

    def read(name):
        return json.loads((folder / 'report' / (name + '.json')).read_text(encoding='utf-8'))

    dates = [dt.date.fromisoformat(day) for day in read('sessions')]
    args = dict(opening=read('opening'), events=read('events'), date=dates[0],
                bars=pl.DataFrame({'symbol': ['600000.SH'], 'trade_date': [dates[0]], 'close': [11.]}),
                calendar=pl.DataFrame({'date': dates, 'market': ['SH'] * len(dates), 'is_open': [True] * len(dates)}),
                dividends=pl.DataFrame(schema=DIVIDEND_SCHEMA),
                suspensions=pl.DataFrame(schema={'symbol': pl.String, 'trade_date': pl.Date}))
    book, result = close_manual_day(**args)
    assert result['imported_count'] == 2
    assert book['cash'] == 89489.
    assert book['cumulative_fees'] == 5.
    assert book['valuation']['market_value'] == 11000.
    assert book['valuation']['equity'] == 100489.
    assert book['valuation']['daily_return'] == pytest.approx(489 / 100000)
    assert book['valuation']['unit_nav'] == pytest.approx(1.00489)
    assert book['valuation']['external_net_flow'] == 0
    assert close_manual_day(**{**args, 'opening': book})[1]['message'] == 'no-op'
