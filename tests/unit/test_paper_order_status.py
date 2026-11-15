import datetime as dt
import json
from dataclasses import dataclass

import polars as pl
import pytest

from quant.data.refresh import SHANGHAI
from quant.execution import paper_order_status as status


@pytest.fixture
def setup(tmp_path, monkeypatch):
    config = tmp_path/'daily.toml'
    config.write_text('auto_trade=false\n[q10]\noutput="primary"\n'
                      '[q10_shadow]\noutput="shadow"\n')
    dates = [dt.date(2026, 11, 27), dt.date(2026, 11, 30), dt.date(2026, 12, 1)]
    monkeypatch.setattr(status, 'read_stock_paper_calendar', lambda _: pl.DataFrame({
        'date': dates, 'is_open': [True]*3}))
    for name in ('primary', 'shadow'):
        account = tmp_path/name
        snapshot = account/'2026-11-30'
        snapshot.mkdir(parents=True)
        (snapshot/'state.json').write_text(json.dumps({'date': '2026-11-30'}))
        (account/'latest_summary.json').write_text(json.dumps({
            'as_of': '2026-11-30', 'auto_trade': False, 'reference_orders': 1}))
        (account/'latest_orders.csv').write_text('as_of,symbol\n2026-11-30,600000.SH\n')
        (snapshot/'orders.csv').write_bytes((account/'latest_orders.csv').read_bytes())
        (account/'latest_orders.md').write_text('2026-11-30 reference order')
    return tmp_path, config


def test_month_end_status_uses_matching_dated_order_evidence(setup):
    root, config = setup
    report = status.collect(root=root, config=config, today=dt.date(2026, 11, 27))
    assert report['next_rebalance'] == '2026-11-30'
    assert report['ready']
    assert report['accounts']['q10']['orders'] == 1


@pytest.mark.parametrize('fault', ['old_summary', 'missing_md', 'mismatched_csv', 'rehearsal'])
def test_stale_or_rehearsal_files_are_not_order_ready(setup, fault):
    root, config = setup
    account = root/'shadow'
    if fault == 'old_summary':
        path = account/'latest_summary.json'
        value = json.loads(path.read_text())
        path.write_text(json.dumps({**value, 'as_of': '2026-10-30'}))
    elif fault == 'missing_md':
        (account/'latest_orders.md').unlink()
    elif fault == 'mismatched_csv':
        (account/'latest_orders.csv').write_text('as_of,symbol\n')
    else:
        (account/'2026-11-30/state.json').write_text(json.dumps({
            'date': '2026-11-30', 'rehearsal': True}))
    report = status.collect(root=root, config=config, today=dt.date(2026, 11, 30))
    assert not report['ready']
    assert report['accounts']['q10']['ready']


def test_watch_alerts_only_after_month_end_cutoff(setup, monkeypatch):
    root, config = setup
    config.write_text(config.read_text() + '[account_30w_top15]\noutput="missing_joint"\n')
    (root/'shadow/latest_orders.md').unlink()
    calls = []

    @dataclass
    class Result:
        channel: str = 'fixture'
        ok: bool = True
        detail: str = 'captured'

    def send(**kwargs):
        calls.append(kwargs)
        return [Result()]

    monkeypatch.setattr('quant.notify.send', send)
    for date, hour, minute in [(27, 23, 0), (30, 22, 29)]:
        report = status.watch(root=root, config=config, notify=True,
            now=dt.datetime(2026, 11, date, hour, minute, tzinfo=SHANGHAI))
        assert not report['alert_due']
    assert not calls
    report = status.watch(root=root, config=config, notify=True,
        now=dt.datetime(2026, 11, 30, 22, 30, tzinfo=SHANGHAI))
    assert report['alert_due']
    assert len(calls) == 1
    assert 'q10_shadow' in calls[0]['body']
    assert 'account_30w_top15' in calls[0]['body']


@pytest.mark.parametrize('fault', ['missing', 'old_summary', 'rehearsal', 'latest_text',
                                   'dated_csv', 'config', 'good'])
def test_joint_account_failure_cannot_be_hidden_by_two_ready_q10_accounts(setup, fault):
    from quant.execution import account_30w_top15_paper as joint

    root, config = setup
    config.write_text(config.read_text() +
        '[account_30w_top15]\noutput="joint"\nconfig="joint.toml"\n')
    (root / 'joint.toml').write_bytes(joint.CONFIG.read_bytes())
    account = root / 'joint'
    folder = account / '2026-11-30'
    folder.mkdir(parents=True)
    if fault != 'missing':
        (account / 'config.toml').write_bytes(joint.CONFIG.read_bytes())
        (folder / 'state.json').write_text(json.dumps(dict(date='2026-11-30',
            auto_trade=False, shadow=True, observation_only=True, rehearsal=False)))
        (folder / 'orders.csv').write_text(
            'as_of,execution_date,symbol,quantity\n2026-11-30,2026-12-01,600000.SH,100\n')
        (folder / 'orders.md').write_text('frozen joint order')
        for suffix in ('csv', 'md'):
            (account / f'latest_orders.{suffix}').write_bytes((folder / f'orders.{suffix}').read_bytes())
        (account / 'latest_summary.json').write_text(json.dumps(dict(status='complete',
            as_of='2026-11-30', auto_trade=False, rehearsal=False, reference_orders=1)))
        joint.publish_order_receipt(account, '2026-11-30',
            dt.datetime(2026, 11, 30, 22, tzinfo=SHANGHAI))
        if fault == 'old_summary':
            (account / 'latest_summary.json').write_text(json.dumps(dict(as_of='2026-10-30')))
        elif fault == 'rehearsal':
            state = json.loads((folder / 'state.json').read_text())
            (folder / 'state.json').write_text(json.dumps({**state, 'rehearsal': True}))
        elif fault == 'latest_text':
            (account / 'latest_orders.md').write_text('different latest order')
        elif fault == 'dated_csv':
            path = folder / 'orders.csv'
            path.write_text(path.read_text().replace('600000.SH', '600001.SH'))
            (account / 'latest_orders.csv').write_bytes(path.read_bytes())
        elif fault == 'config':
            (account / 'config.toml').write_bytes(joint.CONFIG.read_bytes() + b'\n')
    report = status.watch(root=root, config=config,
        now=dt.datetime(2026, 11, 30, 22, 30, tzinfo=SHANGHAI))
    assert report['accounts']['q10']['ready'] and report['accounts']['q10_shadow']['ready']
    if fault == 'good':
        assert report['ready'] and not report['alert_due']
        assert report['accounts']['account_30w_top15']['orders'] == 1
        assert report['accounts']['account_30w_top15']['snapshot_sha256']
        return
    assert not report['ready'] and report['alert_due']
    assert not report['accounts']['account_30w_top15']['ready']


def test_watch_requires_an_explicitly_zoned_clock(setup):
    root, config = setup
    with pytest.raises(ValueError, match='timezone-aware'):
        status.watch(root=root, config=config, now=dt.datetime(2026, 11, 30, 22, 30))
