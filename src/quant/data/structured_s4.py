"""Use unambiguous structured S4 fields only after checking the source excerpt."""
import datetime as dt
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl


class StructuredS4:
    def __init__(self,*,data_root:Path,start:dt.date,end:dt.date,now:dt.datetime):
        self.rows={}
        self.paths=[]
        for table,family in [('repurchase','repurchase'),('stk_holdertrade','insider_trading')]:
            paths=sorted((data_root/'clean'/table).glob('snapshot=*/year=*/data.parquet'))
            if not paths:
                continue
            frame=pl.scan_parquet(paths).filter(pl.col('source_announcement_date').is_between(start,end)
                &(pl.col('available_at')<=now)).collect().sort('observed_at').unique('source_row_id',keep='first',maintain_order=True)
            self.paths.extend(map(str,paths))
            for row in frame.iter_rows(named=True):
                self.rows.setdefault((family,row['ts_code'],row['source_announcement_date']),[]).append(row)

    def lookup(self,*,family,symbol,published,excerpt):
        from quant.data.events_v0 import accept_extraction,fill_explicit_total
        matches=[]
        for row in self.rows.get((family,symbol,published),[]):
            amount,ratio,direction=None,None,None
            if family=='repurchase':
                if row.get('proc')!='完成' or not row.get('end_date') or row['end_date']>published.strftime('%Y%m%d'):
                    continue
                amount=row.get('amount')
                direction='repurchase'
                paid=fill_explicit_total(excerpt,{'parse_status':'unresolved','amount_cny':None},family)
                if not amount or not paid.get('amount_cny') or not math.isclose(amount,paid['amount_cny'],rel_tol=1e-4,abs_tol=1e-6):
                    continue
            else:
                direction={'IN':'buy','DE':'sell'}.get(row.get('in_de'))
                if direction is None or ('增持' in excerpt and '减持' in excerpt):
                    continue
                if direction=='sell' and any(word in excerpt for word in ('未减持','未实施减持')):
                    continue
                volume,price=row.get('change_vol'),row.get('avg_price')
                if volume is not None and price is not None and volume>0 and price>0:
                    amount=volume*price
                ratio=row.get('change_ratio')
            parsed=accept_extraction(excerpt,{'status':'parsed','amount_cny':amount,'ratio_pct':ratio,
                'term_days':None,'direction':direction,'evidence':excerpt})
            if parsed['parse_status']!='parsed' and ratio is not None:
                parsed=accept_extraction(excerpt,{'status':'parsed','amount_cny':amount,'ratio_pct':None,
                    'term_days':None,'direction':direction,'evidence':excerpt})
            if parsed['parse_status']!='parsed':
                continue
            available=row['available_at'].astimezone(ZoneInfo('Asia/Shanghai'))
            known=max(published,(available+dt.timedelta(days=1)).date())
            matches.append({'parsed':parsed,'known_at':known,'source_row_id':row['source_row_id'],
                'raw_path':row['source_raw_path'],'available_at':row['available_at'].isoformat()})
        values={(r['parsed']['amount_cny'],r['parsed']['direction'],r['parsed']['ratio_pct']) for r in matches}
        if len(values)!=1:
            return None
        # Repeated snapshots with equal fields retain the earliest safe availability.
        return min(matches,key=lambda r:r['known_at'])
