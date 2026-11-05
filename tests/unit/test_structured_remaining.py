import datetime as dt
import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest

from quant.data.structured_events import run,chunks
from quant.data.structured_probe_sample import publish_report_trial
from quant.data.storage import RawStore
from quant.data.structured_preliminary import read_preliminary_history
from quant.reporting.structured_coverage import describe_table
from quant.data.structured_native_rows import split_native_rows,MARGIN_AMOUNTS


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


def test_supplier_date_whitespace_keeps_native_values_and_published_consumer_dates(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    path,_,symbols=config(tmp_path)
    class Client:
        def query_raw(self,table,**params):
            date='trade_date' if table=='margin_detail' else 'ann_date'
            return pl.DataFrame({'ts_code':[params.get('ts_code','600000.SH')],
                date:[' 20190115 \t'],'end_date':['20181231 '],'n_income':[123.],
                'revenue':[456.],'update_flag':['1']})
    receipt=run(config=path,output=tmp_path/'capture',connector=Client())
    rule={'date_field':'ann_date','announcement_field':'ann_date'}
    observation=describe_table('stk_holdernumber',receipt['tables']['stk_holdernumber'],rule,
        start=dt.date(2019,1,1),end=dt.date(2019,1,31))
    assert observation['declared_metadata_matches'] and observation['invalid_dates']==0
    saved=pl.read_parquet('data/clean/stk_holdernumber/snapshot=capture/year=2019/data.parquet')
    assert saved['ann_date'].item()==' 20190115 \t'
    assert saved['source_announcement_date'].item()==dt.date(2019,1,15)
    native={k:v for k,v in saved.row(0,named=True).items() if k in Client().query_raw('stk_holdernumber').columns}
    digest=hashlib.sha256(json.dumps(native,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
    assert saved['source_row_id'].item()==digest
    history=read_preliminary_history(tmp_path/'data')
    assert history.height==6
    assert set(history['announcement_date'])=={dt.date(2019,1,15)}
    assert set(history['report_period_end'])=={dt.date(2018,12,31)}


def test_checkpoint_replace_retries_do_not_repeat_api_or_raw_writes(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    path,_,symbols=config(tmp_path)
    output=tmp_path/'capture';summary=output/'summary.json'
    original=Path.replace
    failures=[];pauses=[];calls=[]
    def replace(source,target):
        if Path(target)==summary and len(failures)<2:
            payload=json.loads(source.read_text(encoding='utf-8'))
            if payload['requests']:
                error=PermissionError('temporary Windows reader handle')
                error.winerror=5
                failures.append(error.winerror)
                raise error
        return original(source,target)
    monkeypatch.setattr(Path,'replace',replace)
    def sleep(seconds):
        pauses.append(seconds)
        time.sleep(seconds)
    monkeypatch.setattr('quant.data.realtime_store.time',SimpleNamespace(sleep=sleep))
    class Client:
        def query_raw(self,table,**params):
            calls.append((table,params.copy()))
            field='trade_date' if table=='margin_detail' else 'ann_date'
            return pl.DataFrame({'ts_code':[params.get('ts_code','600000.SH')],field:['20190115']})
    result=run(config=path,output=output,connector=Client())
    assert result['status']=='captured' and failures==[5,5] and pauses.count(.1)>=2
    assert len(calls)==len(result['requests'])==len(list((tmp_path/'data/raw').rglob('*.parquet')))==8
    assert json.loads(summary.read_text(encoding='utf-8'))==result
    assert not list(output.glob('*.tmp'))


def test_permanent_checkpoint_denial_is_bounded_and_retains_last_valid_receipt(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    path,_,_=config(tmp_path)
    output=tmp_path/'capture';summary=output/'summary.json'
    original=Path.replace;attempts=[];calls=[]
    def replace(source,target):
        if Path(target)==summary and json.loads(source.read_text(encoding='utf-8'))['requests']:
            attempts.append(1)
            raise PermissionError('permanent checkpoint denial')
        return original(source,target)
    monkeypatch.setattr(Path,'replace',replace)
    monkeypatch.setattr('quant.data.realtime_store.time',SimpleNamespace(
        sleep=lambda seconds: time.sleep(seconds) if not attempts else None))
    class Client:
        def query_raw(self,table,**params):
            calls.append(table)
            return pl.DataFrame({'ts_code':[params['ts_code']],'ann_date':['20190115']})
    with pytest.raises(PermissionError,match='permanent'):
        run(config=path,output=output,connector=Client())
    assert len(calls)==1 and len(attempts)==22  # page save, then stopped-status save
    assert json.loads(summary.read_text(encoding='utf-8'))['requests']=={}
    assert len(list((tmp_path/'data/raw').rglob('*.parquet')))==1
    assert not list((tmp_path/'data/clean').glob('forecast/snapshot=*'))


def test_margin_markers_retained_in_raw_do_not_shorten_pagination(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    path,_,_=config(tmp_path)
    calls=[]
    class Client:
        def query_raw(self,table,**params):
            if table!='margin_detail':
                return pl.DataFrame({'ts_code':[params.get('ts_code','600000.SH')],'ann_date':['20190115']})
            calls.append(int(params['offset']))
            codes=([f'{i:06d}.SZ' for i in range(999)]+['日期：2019-01-15.BJ']
                if int(params['offset'])==0 else ['400194','T600018.SH'])
            return pl.DataFrame({'ts_code':codes,'trade_date':['20190115']*len(codes),
                **{c:[None if '日期' in s else 1. for s in codes] for c in MARGIN_AMOUNTS}})
    receipt=run(config=path,output=tmp_path/'capture',connector=Client())
    assert calls==[0,1000] and receipt['tables']['margin_detail']['rows']==1001
    quarantines=list(receipt['quarantined_native_rows'].values())
    assert len(quarantines)==1 and quarantines[0]['rows']==1
    assert quarantines[0]['reason']=='supplier_non_record_marker'
    pages=[r for k,r in receipt['requests'].items() if k.startswith('margin_detail/')]
    assert sum(pl.read_parquet(r['raw_path']).height for r in pages)==1002
    saved=pl.read_parquet('data/clean/margin_detail/snapshot=capture/year=2019/data.parquet')
    assert {'400194','T600018.SH'}<=set(saved['ts_code'])
    assert not saved['ts_code'].str.contains('日期').any()


@pytest.mark.parametrize('code,value', [('unknown',None),('日期：2019-01-15.BJ',1.)])
def test_unrecognised_or_valued_margin_marker_fails_instead_of_discarding(code,value):
    frame=pl.DataFrame({'ts_code':[code],**{c:[value] for c in MARGIN_AMOUNTS}})
    with pytest.raises(ValueError,match='Unknown invalid margin'):
        split_native_rows('margin_detail',frame)


def test_all_marker_margin_page_cannot_publish_a_table(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    path,_,_=config(tmp_path)
    class Client:
        def query_raw(self,table,**params):
            if table!='margin_detail':
                return pl.DataFrame({'ts_code':[params.get('ts_code','600000.SH')],'ann_date':['20190115']})
            return pl.DataFrame({'ts_code':['没有找到符合条件的数据！.SZ'],'trade_date':['20190115'],
                **{c:[None] for c in MARGIN_AMOUNTS}})
    with pytest.raises(ValueError,match='No historical rows for margin_detail'):
        run(config=path,output=tmp_path/'capture',connector=Client())
    assert not (tmp_path/'data/clean/margin_detail').exists()


@pytest.mark.parametrize('permanent',[False,True])
def test_clean_directory_publication_retries_without_requery_and_resumes_after_denial(tmp_path,monkeypatch,permanent):
    from quant.data import storage
    monkeypatch.chdir(tmp_path)
    path,_,_=config(tmp_path)
    target=tmp_path/'data/clean/margin_detail/snapshot=capture'
    original=Path.rename;denials=[];pauses=[];calls=[]
    def rename(source,destination):
        if Path(destination).resolve()==target and (permanent or len(denials)<2):
            denials.append(1)
            raise PermissionError('Windows reader holds clean staging directory')
        return original(source,destination)
    class Client:
        def query_raw(self,table,**params):
            calls.append((table,params.copy()))
            field='trade_date' if table=='margin_detail' else 'ann_date'
            return pl.DataFrame({'ts_code':[params.get('ts_code','600000.SH')],field:['20190115']})
    monkeypatch.setattr(Path,'rename',rename)
    monkeypatch.setattr(storage,'time',SimpleNamespace(sleep=pauses.append))
    client=Client();output=tmp_path/'capture'
    if permanent:
        with pytest.raises(PermissionError):run(config=path,output=output,connector=client)
        stopped=json.loads((output/'summary.json').read_text(encoding='utf-8'))
        assert stopped['status']=='stopped' and 'margin_detail' not in stopped['tables']
        assert not target.exists() and (output/'clean_margin_detail/summary.json').is_file()
        assert len(denials)==11 and pauses==[.1]*10
        before={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in (tmp_path/'data/raw').rglob('*.parquet')}
        monkeypatch.setattr(Path,'rename',original)
        result=run(config=path,output=output,resume=True,connector=client)
        assert all(hashlib.sha256(p.read_bytes()).hexdigest()==digest for p,digest in before.items())
    else:
        result=run(config=path,output=output,connector=client)
        assert len(denials)==2 and pauses==[.1,.1]
    assert result['status']=='captured' and len(calls)==8
    assert result['tables']['margin_detail']['rows']==1 and target.is_dir()
