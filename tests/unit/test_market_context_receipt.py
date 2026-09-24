import datetime as dt
import json
import os

import pytest

from quant.research.daily_market_context import completed_observation


@pytest.mark.parametrize('change', [{'status': 'failed'}, {'rehearsal': True},
                                   {'saved_data': True}, {'as_of': '2026-09-22'}])
def test_incomplete_or_stale_receipt_is_not_ready(tmp_path, change):
    path = tmp_path/'2026-09-23_213000'/'summary.json'
    path.parent.mkdir()
    path.write_text(json.dumps(dict(as_of='2026-09-23', status='complete',
                                   rehearsal=False, saved_data=False) | change))
    os.utime(path, (1, 1))
    with pytest.raises(ValueError, match='No completed'):
        completed_observation(dt.date(2026, 9, 23), dt.datetime(2026, 9, 24, tzinfo=dt.timezone.utc), tmp_path)


def test_receipt_cannot_be_used_before_available_time(tmp_path):
    path = tmp_path/'2026-09-23_213000'/'summary.json'
    path.parent.mkdir()
    path.write_text(json.dumps(dict(as_of='2026-09-23', status='complete', rehearsal=False, saved_data=False)))
    clock = dt.datetime(2026, 9, 24, tzinfo=dt.timezone.utc)
    os.utime(path, (clock.timestamp()+1, clock.timestamp()+1))
    with pytest.raises(ValueError, match='No completed'):
        completed_observation(dt.date(2026, 9, 23), clock, tmp_path)
    os.utime(path, (clock.timestamp()-1, clock.timestamp()-1))
    result = completed_observation(dt.date(2026, 9, 23), clock, tmp_path)
    assert result['sha256'] and result['available_at']


def test_missing_current_receipt_clears_stale_current_state(tmp_path):
    import polars as pl
    from quant.research.daily_market_context import run
    data=tmp_path/'data'; root=tmp_path/'context'
    path=data/'clean/trade_calendar/market=SH/data.parquet'
    path.parent.mkdir(parents=True)
    pl.DataFrame({'date':[dt.date(2026,9,24)],'is_open':[True]}).write_parquet(path)
    root.mkdir(); (root/'latest.json').write_text(json.dumps({'status':'complete','date':'2026-09-23','market_state':'bull'}))
    with pytest.raises(ValueError,match='2026-09-24'):
        run(data_root=data,root=root,now=dt.datetime(2026,9,25,0,55,tzinfo=dt.timezone(dt.timedelta(hours=8))),
            require_daily_receipt=True,daily_root=tmp_path/'empty')
    saved=json.loads((root/'latest.json').read_text())
    assert saved['status']=='incomplete' and saved['market_state']=='unknown'
    assert saved['date']=='2026-09-24' and saved['daily_completion'] is None
