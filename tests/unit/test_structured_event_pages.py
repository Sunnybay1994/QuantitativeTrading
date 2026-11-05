import datetime as dt
import hashlib
from pathlib import Path

import polars as pl
import pytest
from requests.exceptions import ConnectionError,ReadTimeout

from quant.data.storage import RawStore
from quant.data.structured_event_pages import pages
from quant.data.structured_events import normalize


def capture(tmp_path, frame, *, fail_at=None, first=None, last=None):
    class Supplier:
        calls=[]
        failed=False

        def query_raw(self, table, **params):
            self.calls.append(params)
            assert int(params['offset'])<=2
            if len(self.calls)==fail_at and not self.failed:
                self.failed=True
                raise TimeoutError('interrupted child window')
            selected=frame.filter(pl.col('ann_date').is_between(pl.lit(params['start_date']),pl.lit(params['end_date'])))
            return selected.slice(int(params['offset']),int(params['limit']))

    client=Supplier()
    args=dict(table='repurchase',rule={'date_field':'ann_date','announcement_field':'ann_date'},
        spec={'page_size':2,'request_pause_seconds':0,'id':'test'},symbol=None,
        first=first or dt.date(2020,1,1),last=last or dt.date(2020,1,4),
        receipt={'requests':{},'tables':{}},client=client,store=RawStore(tmp_path/'raw'),
        save=lambda:None,max_offset=2)
    return args,client


def test_offset_sharding_recovers_all_rows_and_resumes_without_requerying_saved_pages(tmp_path):
    source=pl.DataFrame({'ts_code':['000001.SZ']*8,'ann_date':[
        '20200101','20200101','20200102','20200102','20200103','20200103','20200104','20200104'],
        'value':list(range(8))})
    args,client=capture(tmp_path,source,fail_at=4)
    with pytest.raises(TimeoutError):
        list(pages(**args))
    saved={key:(record.copy(),hashlib.sha256(Path(record['raw_path']).read_bytes()).hexdigest())
        for key,record in args['receipt']['requests'].items()}
    original_calls=list(client.calls[:-1])
    client.calls=[]
    # Resume with the same receipt: original pages are reused, failed page alone is retried.
    normalized=[normalize(frame,table=args['table'],rule=args['rule'],
        observed_at=record['observed_at'],raw_path=record['raw_path'])
        for frame,record in pages(**args)]
    result=pl.concat(normalized).unique('source_row_id',keep='first',maintain_order=True)
    assert sorted(result['value'])==list(range(8))
    assert not any(call in original_calls for call in client.calls)
    for key,(record,digest) in saved.items():
        assert args['receipt']['requests'][key]==record
        assert hashlib.sha256(Path(record['raw_path']).read_bytes()).hexdigest()==digest
    first_record=next(iter(saved.values()))[0]
    assert result.filter(pl.col('value')==0)['source_raw_path'][0]==first_record['raw_path']
    assert args['receipt']['date_splits']
    calls=len(client.calls)
    list(pages(**args))
    assert len(client.calls)==calls


def test_one_day_overflow_fails_instead_of_silently_publishing_truncated_history(tmp_path):
    source=pl.DataFrame({'ts_code':['000001.SZ']*5,'ann_date':['20200101']*5,'value':range(5)})
    args,_=capture(tmp_path,source,first=dt.date(2020,1,1),last=dt.date(2020,1,1))
    with pytest.raises(ValueError,match='single day'):
        list(pages(**args))


def test_resume_rejects_corrupt_parent_page_before_any_new_request(tmp_path):
    source=pl.DataFrame({'ts_code':['000001.SZ'],'ann_date':['20200101'],'value':[1]})
    args,client=capture(tmp_path,source)
    list(pages(**args))
    record=next(iter(args['receipt']['requests'].values()))
    Path(record['raw_path']).write_bytes(b'corrupted')
    count=len(client.calls)
    with pytest.raises(ValueError,match='checksum'):
        list(pages(**args))
    assert len(client.calls)==count


@pytest.mark.parametrize('failure',[ReadTimeout,ConnectionError])
def test_transient_transport_retries_identical_page_before_single_raw_write(tmp_path,monkeypatch,failure):
    source=pl.DataFrame({'ts_code':['000001.SZ'],'ann_date':['20200101'],'value':[1]})
    args,client=capture(tmp_path,source)
    original=client.query_raw
    attempts=[]
    pauses=[]
    saves=[]
    def query(table,**params):
        attempts.append(params.copy())
        if len(attempts)<3:raise failure('supplier transport unavailable')
        return original(table,**params)
    client.query_raw=query
    args['save']=lambda:saves.append(len(args['receipt']['requests']))
    monkeypatch.setattr('quant.data.structured_event_pages.time.sleep',pauses.append)
    result=list(pages(**args))
    assert len(attempts)==3 and attempts[0]==attempts[1]==attempts[2]
    assert pauses==[5,15,0] and saves==[0,0,1]
    assert len(result)==len(args['receipt']['requests'])==1
    assert len(list((tmp_path/'raw').rglob('*.parquet')))==1
    saved=next(iter(args['receipt']['requests'].values()))
    digest=hashlib.sha256(Path(saved['raw_path']).read_bytes()).hexdigest()
    list(pages(**args))
    assert len(attempts)==3 and hashlib.sha256(Path(saved['raw_path']).read_bytes()).hexdigest()==digest


def test_exhausted_transport_stops_without_publishing_or_retrying_business_errors(tmp_path,monkeypatch):
    source=pl.DataFrame({'ts_code':['000001.SZ'],'ann_date':['20200101'],'value':[1]})
    args,client=capture(tmp_path,source)
    calls=[]
    pauses=[]
    def failing(table,**params):
        calls.append(params)
        raise ReadTimeout('unavailable')
    client.query_raw=failing
    monkeypatch.setattr('quant.data.structured_event_pages.time.sleep',pauses.append)
    with pytest.raises(ReadTimeout):list(pages(**args))
    assert len(calls)==3 and pauses==[5,15]
    assert not args['receipt']['requests'] and not list((tmp_path/'raw').rglob('*.parquet'))
    assert len(next(iter(args['receipt']['transport_retries'].values())))==3
    calls.clear()
    def permission_error(table,**params):
        calls.append(params)
        raise ValueError('permission denied or invalid supplier offset')
    client.query_raw=permission_error
    with pytest.raises(ValueError):list(pages(**args))
    assert len(calls)==1 and pauses==[5,15]
