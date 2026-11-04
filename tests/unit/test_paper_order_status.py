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
