"""Resume immutable pages and bisect date windows before the supplier offset cap."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import time

import polars as pl


def pages(*, table, rule, spec, symbol, first, last, receipt, client, store, save,
          max_offset=100000):
    """Yield original pages first so deduplication retains the earliest observation.

    An overflowing window is completed by exhaustive, disjoint child windows.
    Its immutable parent pages remain evidence, including across interrupted runs.
    A single overflowing day fails explicitly rather than publishing a truncation.
    """
    scope=f'{table}/{symbol or "all"}/{first}/{last}'
    offset=0
    page_hashes=set()
    while True:
        key=f'{scope}/{offset}'
        record=receipt['requests'].get(key)
        if record:
            path=Path(record['raw_path'])
            if hashlib.sha256(path.read_bytes()).hexdigest()!=record['sha256']:
                raise ValueError('Immutable raw checksum mismatch')
            frame=pl.read_parquet(path)
        else:
            params={'start_date':first.strftime('%Y%m%d'),'end_date':last.strftime('%Y%m%d'),
                'limit':str(spec['page_size']),'offset':str(offset)}
            if symbol:
                params['ts_code']=symbol
            frame=client.query_raw(table,**params)
            raw=store.write(source='tushare',table=table,frame=frame,
                parameters={**params,'consumer':spec['id']})
            record={'raw_path':str(raw.data_path),'sha256':raw.checksum_sha256,
                'rows':frame.height,'observed_at':dt.datetime.now(dt.timezone.utc).isoformat()}
            receipt['requests'][key]=record
            receipt['current']=key
            save()
            print(json.dumps({'table':table,'start':str(first),'end':str(last),
                'offset':offset,'rows':frame.height}),flush=True)
            time.sleep(spec['request_pause_seconds'])
        if frame.height>spec['page_size']:
            raise ValueError('Supplier ignored bounded page size')
        if frame.height:
            dates=frame[rule['date_field']].str.to_date('%Y%m%d')
            if dates.null_count() or dates.min()<first or dates.max()>last:
                raise ValueError('Supplier response outside frozen date shard')
            if symbol and set(frame['ts_code'])!={symbol}:
                raise ValueError('Supplier symbol scope mismatch')
            if record['sha256'] in page_hashes:
                raise ValueError('Repeated page; pagination completeness is unknown')
            page_hashes.add(record['sha256'])
            yield frame,record
        if frame.height<spec['page_size']:
            return
        offset+=frame.height
        if offset>max_offset:
            if first==last:
                raise ValueError(f'Supplier offset cap exceeded within a single day: {scope}')
            middle=first+(last-first)//2
            children=[(first,middle),(middle+dt.timedelta(days=1),last)]
            receipt.setdefault('date_splits',{})[scope]={
                'reason':'supplier_offset_cap','max_offset':max_offset,
                'children':[[str(a),str(b)] for a,b in children],
                'parent_pages':'retained; identical native rows keep earliest observation'}
            save()
            for a,b in children:
                yield from pages(table=table,rule=rule,spec=spec,symbol=symbol,first=a,last=b,
                    receipt=receipt,client=client,store=store,save=save,max_offset=max_offset)
            return
