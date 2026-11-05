import datetime as dt
import hashlib
import json
from pathlib import Path

import polars as pl
import pytest

from quant.data.storage import RawStore
from quant.data.structured_event_pages import pages
from quant.data.structured_events import normalize
from quant.data.structured_symbol_recovery import load_symbol_recovery


def case(tmp_path,*,symbols=('A','B','DELISTED'),fail_call=None):
    frame=pl.DataFrame({'ts_code':['A']*3+['B']*3,'ann_date':['20200101']*6,'value':range(6)})
    class Supplier:
        calls=[]
        failed=False
        def query_raw(self,table,**params):
            self.calls.append(params.copy())
            if len(self.calls)==fail_call and not self.failed:
                self.failed=True
                raise TimeoutError('interrupted symbol child')
            assert int(params['offset'])<=2
            selected=frame.filter(pl.col('ts_code')==params['ts_code']) if params.get('ts_code') else frame
            return selected.slice(int(params['offset']),int(params['limit']))
    supplier=Supplier()
    args=dict(table='share_float',rule={'date_field':'ann_date','announcement_field':'ann_date'},
        spec={'page_size':2,'request_pause_seconds':0,'id':'test'},symbol=None,
        first=dt.date(2020,1,1),last=dt.date(2020,1,1),receipt={'requests':{}},
        client=supplier,store=RawStore(tmp_path/'raw'),save=lambda:None,max_offset=2,
        symbol_recovery={'table':'share_float','symbols':list(symbols),'catalog_path':'frozen/catalog.json','catalog_sha256':'sha'})
    return args,supplier


def test_complete_symbol_children_keep_cached_global_observations_and_resume(tmp_path):
    args,client=case(tmp_path,fail_call=5)
    with pytest.raises(TimeoutError):list(pages(**args))
    previous={k:r.copy() for k,r in args['receipt']['requests'].items()}
    successful=client.calls[:-1];client.calls=[]
    values=[normalize(frame,table='share_float',rule=args['rule'],observed_at=record['observed_at'],
        raw_path=record['raw_path']) for frame,record in pages(**args)]
    full=pl.concat(values).unique('source_row_id',keep='first',maintain_order=True)
    assert sorted(full['value'])==list(range(6))
    assert not any(c in successful for c in client.calls)
    assert any(c.get('ts_code')=='DELISTED' for c in client.calls)
    first=next(iter(previous.values()))
    assert full.filter(pl.col('value')==0)['source_raw_path'][0]==first['raw_path']
    for key,item in previous.items():
        assert args['receipt']['requests'][key]==item
        assert hashlib.sha256(Path(item['raw_path']).read_bytes()).hexdigest()==item['sha256']
    assert all(item['complete'] for item in args['receipt']['symbol_splits'].values())
    count=len(client.calls);list(pages(**args));assert len(client.calls)==count


def test_missing_prefix_code_or_single_issuer_overflow_cannot_publish_truncation(tmp_path):
    args,client=case(tmp_path,symbols=('A',))
    with pytest.raises(ValueError,match='outside the recovery catalog'):list(pages(**args))
    assert all('ts_code' not in call for call in client.calls)
    args,client=case(tmp_path/'issuer')
    args['symbol']='A';args['max_offset']=0
    with pytest.raises(ValueError,match='single day'):list(pages(**args))


def test_recovery_and_catalog_are_pinned_and_cannot_disappear(tmp_path):
    receipt={}
    assert load_symbol_recovery(tmp_path,receipt) is None
    catalog=tmp_path/'catalog.json';catalog.write_text(json.dumps({'symbols':['A','DELISTED']}))
    path=tmp_path/'single_day_recovery.json'
    spec={'table':'share_float','auto_trade':False,'catalog_path':str(catalog),
        'catalog_sha256':hashlib.sha256(catalog.read_bytes()).hexdigest()}
    path.write_text(json.dumps(spec))
    assert load_symbol_recovery(tmp_path,receipt)['symbols']==['A','DELISTED']
    catalog.write_text(json.dumps({'symbols':['A']}))
    with pytest.raises(ValueError,match='catalog changed'):load_symbol_recovery(tmp_path,receipt)
    catalog.write_text(json.dumps({'symbols':['A','DELISTED']}))
    path.write_text(json.dumps({**spec,'auto_trade':True}))
    with pytest.raises(ValueError,match='request changed'):load_symbol_recovery(tmp_path,receipt)
    path.unlink()
    with pytest.raises(ValueError,match='disappeared'):load_symbol_recovery(tmp_path,receipt)
