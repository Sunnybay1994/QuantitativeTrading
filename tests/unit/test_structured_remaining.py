import datetime as dt
import hashlib
import json

import polars as pl
import pytest

from quant.data.structured_events import run,chunks
from quant.data.structured_probe_sample import publish_report_trial
from quant.data.storage import RawStore


def config(tmp_path):
    symbols=['000001.SZ','600000.SH','920001.BJ']
    catalog=tmp_path/'symbols.json';catalog.write_text(json.dumps({'symbols':symbols}))
    lines=['id="structured_events_remaining_v1"','auto_trade=false','evaluate_factors=false',
        'start=2019-01-01','end=2019-01-31','page_size=1000','request_pause_seconds=0','availability="first observed only"']
    for table in ['forecast','express','stk_holdernumber','margin_detail']:
        date='trade_date' if table=='margin_detail' else 'ann_date'
        lines += [f'[tables.{table}]',f'date_field="{date}"',f'announcement_field="{date}"',
            'chunk="all"','consumer="fixed preregistered data consumer"']
        if table in ('forecast','express'):
            lines += ['symbols_file='+json.dumps(str(catalog)),
                'symbols_sha256='+json.dumps(hashlib.sha256(catalog.read_bytes()).hexdigest())]
    path=tmp_path/'config.toml';path.write_text('\n'.join(lines))
    return path,catalog,symbols


def test_all_history_by_frozen_symbol_includes_delisted_and_bj_and_resumes(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    path,_,symbols=config(tmp_path)
    class Client:
        calls=[]
        def query_raw(self,table,**params):
            self.calls.append((table,params))
            if table in ('forecast','express'):assert params['ts_code'] in symbols
            field='trade_date' if table=='margin_detail' else 'ann_date'
            return pl.DataFrame({'ts_code':[params.get('ts_code','600000.SH')],field:['20190115'],'value':[1.]})
    client=Client();output=tmp_path/'capture'
    receipt=run(config=path,output=output,connector=client)
    assert receipt['status']=='captured' and len(client.calls)==8
    for name in ('forecast','express'):
        assert receipt['tables'][name]['symbols']==3
        assert {params['ts_code'] for table,params in client.calls if table==name}==set(symbols)
    run(config=path,output=output,resume=True,connector=client)
    assert len(client.calls)==8
    f=pl.read_parquet('data/clean/forecast/snapshot=capture/year=2019/data.parquet')
    assert f['available_at'].min()>dt.datetime(2019,1,16,tzinfo=dt.timezone.utc)


def test_catalog_drift_fails_before_fetch_and_unknown_chunks_are_rejected(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    path,catalog,_=config(tmp_path);catalog.write_text('{"symbols":["600000.SH"]}')
    class Client:
        def query_raw(self,*a,**k):pytest.fail('Changed catalog queried source')
    with pytest.raises(ValueError,match='catalog changed'):
        run(config=path,output=tmp_path/'capture',connector=Client())
    with pytest.raises(ValueError,match='Unknown registered'):
        list(chunks(dt.date(2019,1,1),dt.date(2019,2,1),'unknown'))


def test_trial_sample_is_published_at_raw_observation_without_new_requests(tmp_path):
    frame=pl.DataFrame({'ts_code':['000001.SZ'],'report_date':['20261031'],'eps':[1.2]})
    observed=dt.datetime(2026,11,5,1,2,3,tzinfo=dt.timezone.utc)
    raw=RawStore(tmp_path/'raw').write(source='tushare',table='report_rc',frame=frame,
        parameters={'limit':'5'},fetched_at=observed)
    permissions=tmp_path/'permissions.json'
    permissions.write_text(json.dumps({'tables':{'report_rc':{'raw_path':str(raw.data_path),
        'sha256':raw.checksum_sha256,'checked_at':(observed-dt.timedelta(seconds=1)).isoformat(),
        'parameters':{'limit':'5'}}}}))
    result=publish_report_trial(permissions=permissions,data_root=tmp_path/'data')
    assert not result['historical_full_coverage'] and not result['counts_toward_D1_full_tables']
    assert result['new_api_calls']==0
    path=tmp_path/'data/clean/report_rc/snapshot=structured_probe_trial_20261105/data.parquet'
    saved=pl.read_parquet(path)
    assert saved['available_at'].item()==observed
    assert publish_report_trial(permissions=permissions,data_root=tmp_path/'data')==result
