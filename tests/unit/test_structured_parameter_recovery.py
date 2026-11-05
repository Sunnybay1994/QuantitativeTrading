import datetime as dt
import hashlib
import json
from pathlib import Path
import tomllib

import polars as pl
import pytest

from quant.data.storage import RawStore
from quant.data.structured_event_pages import pages
from quant.data.structured_events import run
from quant.data.structured_parameter_recovery import load_parameter_recovery,parameter_pages
from quant.data.structured_symbol_recovery import load_symbol_recovery


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def setup_capture(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    output=tmp_path/'capture';output.mkdir()
    config=tmp_path/'config.toml'
    lines=['id="structured_events_v1"','auto_trade=false','evaluate_factors=false',
        'start=2024-04-01','end=2024-06-30','page_size=2','request_pause_seconds=0',
        'availability="first observed only"']
    for table in ('repurchase','stk_holdertrade','share_float','fund_share'):
        field='float_date' if table=='share_float' else 'ann_date'
        lines.extend([f'[tables.{table}]',f'date_field="{field}"',
            'announcement_field="ann_date"','chunk="month"','consumer="frozen consumer"'])
    config.write_text('\n'.join(lines))
    spec=tomllib.loads(config.read_text())
    catalog=output/'catalog.json';catalog.write_text(json.dumps({'symbols':['A','B','DELISTED']}))
    symbol={'table':'share_float','auto_trade':False,'catalog_path':str(catalog),'catalog_sha256':sha(catalog)}
    (output/'single_day_recovery.json').write_text(json.dumps(symbol))
    frame=pl.DataFrame({'ts_code':['A','A','B','A'],
        'ann_date':['20240301','20240401','20240402','20240501'],
        'float_date':['20240401','20240501','20240502','20240601'],'value':[1,2,3,4]})
    class Client:
        def __init__(self):self.calls=[];self.fail_b=False
        def query_raw(self,table,**params):
            self.calls.append((table,params.copy()))
            if table!='share_float':
                return pl.DataFrame({'ts_code':['ETF'],'ann_date':[params['start_date']],'value':[1]})
            if self.fail_b and params.get('ts_code')=='B':
                self.fail_b=False
                raise TimeoutError('interrupted suffix')
            selected=frame.filter(pl.col('float_date').is_between(pl.lit(params['start_date']),pl.lit(params['end_date'])))
            if params.get('ts_code'):selected=selected.filter(pl.col('ts_code')==params['ts_code'])
            elif params['start_date']>='20240501' and int(params['offset'])>=2:
                raise ValueError('ts_code or ann_date required')
            return selected.slice(int(params['offset']),int(params['limit']))
    client=Client()
    receipt={'requests':{},'tables':{'repurchase':{},'stk_holdertrade':{}},
        'status':'stopped','config_sha256':sha(config)}
    args=dict(table='share_float',rule=spec['tables']['share_float'],spec=spec,
        symbol=None,receipt=receipt,client=client,store=RawStore(tmp_path/'data/raw'),save=lambda:None)
    list(pages(**args,first=dt.date(2024,4,1),last=dt.date(2024,4,30)))
    with pytest.raises(ValueError,match='required'):
        list(pages(**args,first=dt.date(2024,5,1),last=dt.date(2024,5,31)))
    stopped=output/'stopped.json';stopped.write_text(json.dumps(receipt))
    recovery={**symbol,'first':'2024-05-01','last':'2024-06-30','failed_last':'2024-05-31',
        'failed_offset':2,'original_config_sha256':sha(config),
        'stopped_summary_path':str(stopped),'stopped_summary_sha256':sha(stopped)}
    path=output/'parameter_recovery.json';path.write_text(json.dumps(recovery))
    (output/'summary.json').write_text(json.dumps(receipt))
    client.calls=[]
    return output,config,spec,receipt,client,path,args


def test_run_reuses_original_pages_and_resumes_entire_suffix_without_global_requery(tmp_path,monkeypatch):
    output,config,spec,receipt,client,path,args=setup_capture(tmp_path,monkeypatch)
    original={k:v.copy() for k,v in receipt['requests'].items()}
    client.fail_b=True
    with pytest.raises(TimeoutError):run(config=config,output=output,resume=True,connector=client)
    succeeded=client.calls[:-1];client.calls=[]
    result=run(config=config,output=output,resume=True,connector=client)
    assert result['status']=='captured' and result['parameter_split']['complete']
    assert not any(call in succeeded for call in client.calls)
    assert all(p.get('ts_code') for t,p in client.calls if t=='share_float')
    assert {p['ts_code'] for t,p in client.calls if t=='share_float'}=={'B','DELISTED'}
    assert all(p['start_date']=='20240501' and p['end_date']=='20240630'
        for t,p in client.calls if t=='share_float')
    full=pl.read_parquet(output.parent/'data/clean/share_float/snapshot=capture/year=2024/data.parquet')
    assert sorted(full['value'])==[1,2,3,4]
    old=original['share_float/all/2024-05-01/2024-05-31/0']
    assert full.filter(pl.col('value')==2)['source_raw_path'].item()==old['raw_path']
    assert full.filter(pl.col('value')==2)['observed_at'].item()==dt.datetime.fromisoformat(old['observed_at'])
    for key,record in original.items():
        assert result['requests'][key]==record and sha(Path(record['raw_path']))==record['sha256']
    count=len(client.calls)
    run(config=config,output=output,resume=True,connector=client)
    assert len(client.calls)==count


def test_recovery_descriptor_pin_catalog_and_stopped_receipt_cannot_change(tmp_path,monkeypatch):
    output,config,spec,receipt,client,path,args=setup_capture(tmp_path,monkeypatch)
    symbol=load_symbol_recovery(output,receipt)
    assert load_parameter_recovery(output,receipt,spec,symbol)['symbols']==['A','B','DELISTED']
    original=path.read_bytes();path.write_bytes(original+b' ')
    with pytest.raises(ValueError,match='request changed'):
        load_parameter_recovery(output,receipt,spec,symbol)
    path.write_bytes(original)
    receipt['requests']['share_float/all/2024-05-01/2024-05-31/0']['observed_at']='changed'
    with pytest.raises(ValueError,match='records changed'):
        load_parameter_recovery(output,receipt,spec,symbol)
    path.unlink()
    with pytest.raises(ValueError,match='disappeared'):
        load_parameter_recovery(output,receipt,spec,symbol)
    assert not client.calls


@pytest.mark.parametrize('change,match',[
    ({'last':'2024-07-01'},'outside'),({'first':'2024-05-02'},'outside'),
    ({'failed_offset':1},'unsaved'),({'failed_offset':4},'contiguous'),
    ({'catalog_sha256':'changed'},'catalog'),({'auto_trade':True},'scope'),
    ({'original_config_sha256':'changed'},'scope'),({'stopped_summary_sha256':'changed'},'receipt changed')])
def test_invalid_recovery_fails_before_any_supplier_query(tmp_path,monkeypatch,change,match):
    output,config,spec,receipt,client,path,args=setup_capture(tmp_path,monkeypatch)
    path.write_text(json.dumps({**json.loads(path.read_text()),**change}))
    with pytest.raises(ValueError,match=match):
        load_parameter_recovery(output,receipt,spec,load_symbol_recovery(output,receipt))
    assert not client.calls


def test_unknown_cached_prefix_code_blocks_new_child_requests(tmp_path,monkeypatch):
    output,config,spec,receipt,client,path,args=setup_capture(tmp_path,monkeypatch)
    recovery=load_parameter_recovery(output,receipt,spec,load_symbol_recovery(output,receipt))
    recovery['symbols']=['A']
    with pytest.raises(ValueError,match='outside the recovery catalog'):
        list(parameter_pages(table='share_float',rule=args['rule'],spec=spec,receipt=receipt,
            client=client,store=args['store'],save=lambda:None,recovery=recovery))
    assert not client.calls
