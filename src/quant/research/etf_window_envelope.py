"""Separate opening prints from regular minutes and build a conservative price envelope."""
import datetime as dt
import hashlib
import math
from pathlib import Path

import polars as pl


def valid_opening(row):
    if not row.get('is_opening_row') or row.get('adjustment')!='none':return False
    stamp=row['bar_time']
    if stamp.time()!=dt.time(9,30) or stamp.date()!=row['trade_date']:return False
    if any(row[k] is None or not math.isfinite(row[k]) or row[k]<=0 for k in ['open','high','low','close','volume','amount']):return False
    return (row['low']<=min(row['open'],row['close'])<=max(row['open'],row['close'])<=row['high'] and
            row['low']-.0011<=row['amount']/row['volume']<=row['high']+.0011)


def build(output,source,symbols,dates):
    daily_path=source/'bars.parquet';inst_path=source/'instruments.parquet'
    bars=pl.read_parquet(daily_path);instruments=pl.read_parquet(inst_path)
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [daily_path,inst_path,Path(__file__)]}
    currency=dict(instruments.select('symbol','currency').iter_rows())
    daily={(r['trade_date'],r['symbol']):r for r in bars.to_dicts()}
    checks=pl.read_csv(output/'minute_source_checks.csv',try_parse_dates=True).to_dicts()
    components=[];first_minutes=[]
    for r in checks:
        provider=r['source'];adjustment=('none' if provider.startswith('futu:') or provider in ['tdx','baostock'] else 'unverified')
        components.append({**r,'component':'regular_first5m' if provider.startswith('futu:') else 'native_first5m',
                           'adjustment':adjustment,'opening_included':False if provider.startswith('futu:') else None})
    for symbol in symbols:
        for dataset in sorted(Path('data/clean/futu_minute').glob('*')):
            paths=sorted(dataset.glob(f'symbol={symbol}/year=*/data.parquet'))
            if not paths:continue
            for p in paths:hashes[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
            frame=pl.concat([pl.read_parquet(p) for p in paths]);provider='futu:'+dataset.name
            for day in dates:
                window=frame.filter((pl.col('trade_date')==day)&(pl.col('bar_time').dt.hour()==9)&pl.col('bar_time').dt.minute().is_between(30,35))
                opening=window.filter(pl.col('is_opening_row'))
                regular=next(r for r in checks if r['source']==provider and r['date']==day and r['symbol']==symbol)
                if opening.height==1:
                    row=opening.row(0,named=True);ok=valid_opening(row)
                    components.append(dict(symbol=symbol,date=day,source=provider,freq='opening',component='opening_row',
                        adjustment=row['adjustment'],opening_included=True,status='valid' if ok else 'invalid_opening',
                        **{k:row[k] for k in ['open','high','low','close','volume','amount']}))
                    if ok and regular['status']=='valid':
                        combined={**regular,'component':'opening_plus_regular_first5m','adjustment':'none','opening_included':True}
                        combined.update(open=row['open'],high=max(row['high'],regular['high']),low=min(row['low'],regular['low']),
                                        volume=row['volume']+regular['volume'],amount=row['amount']+regular['amount'])
                        components.append(combined)
                # The component rows remain inspectable down to each source minute.
                for r in window.to_dicts():
                    first_minutes.append(dict(date=day,symbol=symbol,source=provider,time=str(r['bar_time']),
                        opening=r['is_opening_row'],adjustment=r['adjustment'],**{k:r[k] for k in ['open','high','low','close','volume','amount']}))
        path=Path(f'data/clean/bar_intraday/freq=1m/source=tdx/symbol={symbol}/data.parquet')
        if path.exists():
            hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
            tdx=pl.read_parquet(path).filter(pl.col('trade_date').is_in(dates)&(pl.col('bar_start').dt.hour()==9)&pl.col('bar_start').dt.minute().is_between(30,34))
            for r in tdx.to_dicts():first_minutes.append(dict(date=r['trade_date'],symbol=symbol,source='tdx',time=str(r['bar_end']),
                opening=False,adjustment='native_unadjusted',**{k:r[k] for k in ['open','high','low','close','volume','amount']}))
    for r in components:
        b=daily.get((r['date'],r['symbol']));inside=bool(b and r.get('low') is not None and r.get('high') is not None and
            b['low']-.0011<=r['low']<=r['high']<=b['high']+.0011)
        r.update(currency=currency[r['symbol']],inside_daily_range=inside,
                 envelope_eligible=r['status']=='valid' and inside and r['adjustment']=='none' and currency[r['symbol']]=='CNY' and r['component']!='opening_row')
    required=pl.read_csv(output/'required_windows.csv',try_parse_dates=True).to_dicts();envelopes=[];diagnostics=[]
    for r in required:
        candidates=[c for c in components if c['date']==r['date'] and c['symbol']==r['symbol'] and c['envelope_eligible']]
        envelope=dict(date=r['date'],symbol=r['symbol'],strict_covered=r['covered'],strict_reason=r['reason'],
            envelope_eligible=bool(candidates),reason='valid_source_envelope' if candidates else 'no_eligible_window',
            high=max(c['high'] for c in candidates) if candidates else None,
            low=min(c['low'] for c in candidates) if candidates else None,
            eligible_components=len(candidates),eligible_sources=len({c['source'] for c in candidates}))
        envelopes.append(envelope)
        if r['source_conflict']:
            # Compare native windows with Futu including its separately recorded opening print.
            same=[c for c in candidates if not c['source'].startswith('futu:') or c['component']=='opening_plus_regular_first5m']
            aligned=bool(same and any(c['source'].startswith('futu:') for c in same) and
                         max(c['high'] for c in same)-min(c['high'] for c in same)<=.0011 and
                         max(c['low'] for c in same)-min(c['low'] for c in same)<=.0011)
            diagnostics.append(dict(date=r['date'],symbol=r['symbol'],opening_row_explains_extrema=aligned,
                max_high_difference=max(c['high'] for c in same)-min(c['high'] for c in same) if same else None,
                max_low_difference=max(c['low'] for c in same)-min(c['low'] for c in same) if same else None,
                interpretation='opening_component_alignment_only' if aligned else 'residual_source_extrema_difference_not_explained'))
    for name,rows in [('source_window_components',components),('source_first_minutes',first_minutes),
                      ('envelope_windows',envelopes),('conflict_decomposition',diagnostics)]:
        pl.from_dicts(rows,infer_schema_length=None).write_csv(output/f'{name}.csv')
    return dict(eligible_windows=sum(r['envelope_eligible'] for r in envelopes),strict_covered=sum(r['covered'] for r in required),
        opening_explained_conflicts=sum(r['opening_row_explains_extrema'] for r in diagnostics),
        residual_conflicts=sum(not r['opening_row_explains_extrema'] for r in diagnostics)),hashes
