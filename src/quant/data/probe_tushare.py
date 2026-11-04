"""D1: one bounded call per requested table, preserving raw and permission evidence."""
import argparse
import datetime as dt
import json
from pathlib import Path
import time

from quant.data.connectors.tushare import TushareConnector
from quant.data.stock_paper_inputs import read_stock_paper_calendar
from quant.data.storage import RawStore

TABLES=('forecast','express','repurchase','stk_holdertrade','share_float',
        'margin_detail','stk_holdernumber','fund_share','report_rc')


def run(*,output,as_of,connector=None,pause=1.1):
    if output.exists():
        existing=json.loads(output.read_text(encoding='utf-8'))
        if existing['as_of']!=str(as_of):
            raise ValueError('Existing probe belongs to another date')
        result=existing
    else:
        result={'as_of':str(as_of),'status':'running','auto_trade':False,'tables':{}}
    calendar=read_stock_paper_calendar(Path('data'))
    day=calendar.filter((calendar['date']<as_of)&calendar['is_open'])['date'].max()
    if day is None:
        raise ValueError('No prior exchange session for bounded daily-table probe')
    end=day.strftime('%Y%m%d')
    client=connector or TushareConnector()
    store=RawStore(Path('data/raw'))
    output.parent.mkdir(parents=True,exist_ok=True)
    def save():
        temporary=output.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
        temporary.replace(output)
    save()
    for table in TABLES:
        if table in result['tables']:
            continue
        params={'start_date':'20190101','end_date':end,'limit':'5'}
        if table in ('forecast','express','stk_holdertrade','share_float','stk_holdernumber','report_rc'):
            params['ts_code']='000001.SZ'
        if table=='forecast':
            params['ts_code']='000002.SZ'
        if table=='margin_detail':
            params={'trade_date':end,'limit':'5'}
        if table=='fund_share':
            params={'ts_code':'510300.SH','start_date':'20190101','end_date':end,'limit':'5'}
        record={'parameters':params,'calls':1,'checked_at':dt.datetime.now(dt.timezone.utc).isoformat()}
        try:
            frame=client.query_raw(table,**params)
            raw=store.write(source='tushare',table=table,frame=frame,
                parameters={**params,'consumer':'d1_permission_probe_v1'})
            record.update(status='available' if frame.height else 'available_empty',rows=frame.height,
                fields={name:str(dtype) for name,dtype in frame.schema.items()},raw_path=str(raw.data_path),sha256=raw.checksum_sha256)
        except Exception as exc:
            message=str(exc)
            reason=('permission_denied' if '权限' in message or 'permission' in message.lower() else
                'rate_limited' if '频率' in message or '每分钟' in message else 'request_failed')
            record.update(status=reason,error_type=type(exc).__name__)
            # Supplier error text can echo request details; do not persist credentials.
        result['tables'][table]=record
        save()
        print(json.dumps({'table':table,'status':record['status'],'rows':record.get('rows')}),flush=True)
        if pause:
            time.sleep(pause)
    result['status']='probed'
    save()
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--as-of',type=dt.date.fromisoformat,default=dt.date.today())
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    run(output=args.output or Path(f'artifacts/data/tushare_permissions_{args.as_of:%Y%m%d}.json'),as_of=args.as_of)
