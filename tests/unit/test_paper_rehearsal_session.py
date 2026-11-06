import datetime as dt
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from quant.execution.paper_rehearsal import rehearse_account, resolve_session

SH = ZoneInfo('Asia/Shanghai')


@pytest.fixture
def calendar_root(tmp_path):
    start = dt.date(2026,9,1)
    days = [start+dt.timedelta(days=n) for n in range(100)]
    for market in ('SH','SZ'):
        folder = tmp_path/'clean/trade_calendar'/f'market={market}'
        folder.mkdir(parents=True)
        pl.DataFrame({'date':days,'is_open':[d.weekday()<5 for d in days]}).write_parquet(folder/'data.parquet')
    return tmp_path


@pytest.mark.parametrize('clock, expected', [
    ('2026-11-06T10:00:00','2026-11-05'),
    ('2026-11-06T20:59:59','2026-11-05'),
    ('2026-11-06T21:00:00','2026-11-06'),
    ('2026-11-07T10:00:00','2026-11-06'),
    ('2026-11-08T22:10:00','2026-11-06'),
    ('2026-11-09T10:00:00','2026-11-06'),
    ('2026-11-09T22:10:00','2026-11-09'),
])
def test_early_and_delayed_weekend_job_uses_a_ready_trading_session(calendar_root,clock,expected):
    selected = resolve_session(data_root=calendar_root,
        now=dt.datetime.fromisoformat(clock).replace(tzinfo=SH))
    assert str(selected) == expected


@pytest.mark.parametrize('requested', ['2026-11-01','2026-11-07','2026-11-09'])
def test_explicit_nontrading_or_unfinished_day_is_rejected(calendar_root,requested):
    with pytest.raises(ValueError,match='completed exchange session'):
        resolve_session(data_root=calendar_root,end=dt.date.fromisoformat(requested),
                        now=dt.datetime(2026,11,9,10,tzinfo=SH))


def test_explicit_historical_open_session_is_preserved(calendar_root):
    day = dt.date(2026,11,3)
    assert resolve_session(data_root=calendar_root,end=day,
        now=dt.datetime(2026,11,6,10,tzinfo=SH)) == day


def test_missing_calendar_never_starts_a_calendar_download(tmp_path,monkeypatch):
    def unexpected(*args,**kwargs):
        pytest.fail('Rehearsal must not trigger new calendar capture')
    monkeypatch.setattr('quant.data.refresh.TushareConnector',unexpected)
    with pytest.raises(ValueError,match='Saved calendar'):
        resolve_session(data_root=tmp_path,now=dt.datetime(2026,11,6,10,tzinfo=SH))
    assert not (tmp_path/'raw').exists()


def test_a_successful_old_snapshot_cannot_pass_the_requested_rehearsal_day(tmp_path,monkeypatch):
    account = tmp_path/'account'
    source = account/'2026-11-05'
    source.mkdir(parents=True)
    (source/'state.json').write_text('{}',encoding='utf-8')

    def stale_run(**kwargs):
        for name in ('latest_orders.md','report.md'):
            (kwargs['output']/name).write_text('old snapshot',encoding='utf-8')
        return {'as_of':'2026-11-05'}

    monkeypatch.setattr('quant.execution.paper_rehearsal.run_q10',stale_run)
    receipt = rehearse_account(account=account,config=tmp_path/'config.toml',
                              end=dt.date(2026,11,6),data_root=tmp_path)
    assert receipt['status'] == 'failed' and 'did not advance' in receipt['error']
    assert receipt['pushed'] is False and receipt['auto_trade'] is False
    assert (source/'state.json').read_text(encoding='utf-8') == '{}'
