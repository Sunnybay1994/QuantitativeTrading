import datetime as dt
import hashlib
import json
import os
from pathlib import Path

import polars as pl
import pytest

from quant.data import market_snapshot as snapshot


def fixture(tmp_path):
    now=dt.datetime(2026,9,28,11,25,tzinfo=snapshot.TZ)
    previous=dt.date(2026,9,24)
    calendar=tmp_path/'data/clean/trade_calendar/market=SH/data.parquet'
    calendar.parent.mkdir(parents=True)
    pl.DataFrame({'date':[dt.date(2026,9,23),previous,dt.date(2026,9,25),now.date()],
                  'is_open':[True,True,False,True]}).write_parquet(calendar)
    receipt=tmp_path/'receipt.json'
    receipt.write_text(json.dumps(dict(as_of=str(previous),status='complete',rehearsal=False,saved_data=False)))
    os.utime(receipt,(now.timestamp()-1,now.timestamp()-1))
    report=tmp_path/'history/report.md';report.parent.mkdir();report.write_text('history')
    pl.DataFrame({'symbol':['600000.SH'],'trade_date':[previous]}).write_parquet(report.parent/'latest_reference.parquet')
    pointer=dict(status='complete',date=str(previous),effective_date=str(now.date()),report=str(report),
        daily_completion=dict(path=str(receipt),sha256=hashlib.sha256(receipt.read_bytes()).hexdigest()))
    return now,pointer,tmp_path/'latest.json'


@pytest.mark.parametrize('case',['incomplete','missing_report','missing_receipt','stale_context','stale_reference','changed_receipt','missing_pointer'])
def test_invalid_reference_never_requests_quotes(tmp_path,monkeypatch,case):
    now,pointer,path=fixture(tmp_path)
    if case=='incomplete':pointer=dict(status='incomplete',reason='No completed observation')
    elif case=='missing_report':pointer.pop('report')
    elif case=='missing_receipt':pointer['daily_completion']=None
    elif case=='stale_context':pointer['date']='2026-09-23'
    elif case=='stale_reference':
        pl.DataFrame({'symbol':['600000.SH'],'trade_date':[dt.date(2026,9,23)]}).write_parquet(tmp_path/'history/latest_reference.parquet')
    elif case=='changed_receipt':pointer['daily_completion']['sha256']='0'*64
    if case!='missing_pointer':path.write_text(json.dumps(pointer))
    def forbidden(*args,**kwargs):raise AssertionError('Network must not be touched')
    monkeypatch.setattr(snapshot,'PublicMarket',forbidden)
    result=snapshot.capture(tmp_path/'capture',context_path=path,data_root=tmp_path/'data',now=now)
    assert result['status']=='incomplete' and result['market_state']=='unknown'
    assert result['requested']==0 and result['reason']
    assert not (tmp_path/'capture/market.sqlite').exists()
    assert json.loads((tmp_path/'capture/summary.json').read_text())==result


def test_correct_previous_exchange_session_is_accepted(tmp_path):
    now,pointer,path=fixture(tmp_path);path.write_text(json.dumps(pointer))
    history,reference,digest,symbols=snapshot._reference(path,tmp_path/'data',now)
    assert history==tmp_path/'history' and symbols==['600000.SH']
    assert digest==hashlib.sha256(reference.read_bytes()).hexdigest()
