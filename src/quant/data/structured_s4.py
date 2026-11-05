"""Use unambiguous structured S4 fields only after checking the source excerpt."""
import datetime as dt
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
from quant.data.event_family_inputs import read_event_source


class StructuredS4:
    def __init__(self,*,data_root:Path,start:dt.date,end:dt.date,now:dt.datetime):
        self.rows={}
        self.paths=[]
        for table,family in [('repurchase','repurchase'),('stk_holdertrade','insider_trading')]:
            source,paths=read_event_source(data_root,table,known_at=now)
            if source is None:
                continue
            frame=source.filter(pl.col('source_announcement_date').is_between(start,end)).collect()
            # Supplier columns can be strings (including unresolved ranges).
            # Parse native numbers only; nonnumeric/nonfinite values stay missing.
            numeric=('amount',) if table=='repurchase' else ('change_vol','avg_price','change_ratio')
            frame=frame.with_columns(pl.col(name).cast(pl.Float64,strict=False) for name in numeric if name in frame.columns)
            frame=frame.with_columns(pl.when(pl.col(name).is_finite()).then(pl.col(name)).otherwise(None).alias(name)
                for name in numeric if name in frame.columns)
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
            available=max(row['available_at'],row['observed_at']).astimezone(ZoneInfo('Asia/Shanghai'))
            known=max(published,(available+dt.timedelta(days=1)).date())
            matches.append({'parsed':parsed,'known_at':known,'source_row_id':row['source_row_id'],
                'raw_path':row['source_raw_path'],'available_at':row['available_at'].isoformat()})
        values={(r['parsed']['amount_cny'],r['parsed']['direction'],r['parsed']['ratio_pct']) for r in matches}
        if len(values)!=1:
            return None
        # Repeated snapshots with equal fields retain the earliest safe availability.
        return min(matches,key=lambda r:r['known_at'])
