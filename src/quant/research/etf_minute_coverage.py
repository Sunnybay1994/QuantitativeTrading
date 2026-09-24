"""Read-only opening-window inventory; absent windows never become portfolio returns."""
import datetime as dt
import hashlib
import math
import json
import tomllib
from pathlib import Path

import polars as pl


def window_quality(frame, day, frequency):
    part=frame.filter((pl.col('trade_date')==day)&(pl.col('bar_start').dt.hour()==9)&
                      pl.col('bar_start').dt.minute().is_between(30,34)).sort('bar_start')
    expected=5 if frequency=='1m' else 1
    if part.height!=expected: return None,'missing_or_duplicate_window'
    rows=part.to_dicts();duration=1 if frequency=='1m' else 5
    if ([r['bar_start'].minute for r in rows] != list(range(30,35,duration)) or
        any(r['bar_end']-r['bar_start']!=dt.timedelta(minutes=duration) for r in rows)):
        return None,'noncontiguous_window'
    for r in rows:
        if any(r[k] is None or not math.isfinite(r[k]) for k in ['open','high','low','close']):
            return None,'missing_or_nonfinite_price'
        if not (0<r['low']<=min(r['open'],r['close'])<=max(r['open'],r['close'])<=r['high']):
            return None,'invalid_ohlc'
        if any(r[k] is None or not math.isfinite(r[k]) or r[k]<=0 for k in ['volume','amount']):
            return None,'missing_or_nonpositive_turnover'
        if not r['low']-.0011 <= r['amount']/r['volume'] <= r['high']+.0011:
            return None,'vwap_outside_ohlc'
    return dict(open=rows[0]['open'],high=max(r['high'] for r in rows),low=min(r['low'] for r in rows),
                close=rows[-1]['close'],volume=sum(r['volume'] for r in rows),amount=sum(r['amount'] for r in rows)), 'valid'


def inspect(output, source, symbols, dates, end):
    inventory=[];checks=[];hashes={};usable={}
    for symbol in symbols:
        for provider in ['tdx','baostock','yahoo']:
            for freq in ['5m','1m']:
                path=Path(f'data/clean/bar_intraday/freq={freq}/source={provider}/symbol={symbol}/data.parquet')
                if not path.exists():continue
                frame=pl.read_parquet(path);hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
                inventory.append(dict(symbol=symbol,source=provider,freq=freq,path=str(path),rows=frame.height,
                    start=frame['trade_date'].min(),end=frame['trade_date'].max(),days=frame['trade_date'].n_unique()))
                for date in dates:
                    window,reason=window_quality(frame,date,freq)
                    checks.append(dict(symbol=symbol,date=date,source=provider,freq=freq,status=reason,**(window or {})))
                    if window is not None:usable.setdefault((date,symbol),[]).append(dict(source=provider,freq=freq,**window))
        # Existing Futu history uses minute END labels and preserves auction rows.
        # It is a different saved layout, not a request for new network data.
        for dataset in sorted(Path('data/clean/futu_minute').glob('*')):
            files=sorted(dataset.glob(f'symbol={symbol}/year=*/data.parquet'))
            if not files:continue
            parts=[]
            for path in files:
                hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
                parts.append(pl.read_parquet(path))
            frame=pl.concat(parts)
            if frame['adjustment'].unique().to_list()!=['none']:
                raise ValueError('Adjusted Futu minute prices cannot execute unadjusted account')
            frame=frame.filter(~pl.col('is_opening_row')).with_columns(
                (pl.col('bar_time')-dt.timedelta(minutes=1)).alias('bar_start'),pl.col('bar_time').alias('bar_end'))
            provider='futu:'+dataset.name
            inventory.append(dict(symbol=symbol,source=provider,freq='1m',path=str(dataset),rows=frame.height,
                start=frame['trade_date'].min(),end=frame['trade_date'].max(),days=frame['trade_date'].n_unique()))
            for date in dates:
                window,reason=window_quality(frame,date,'1m')
                checks.append(dict(symbol=symbol,date=date,source=provider,freq='1m',status=reason,**(window or {})))
                if window is not None:usable.setdefault((date,symbol),[]).append(dict(source=provider,freq='1m',**window))
    required=[]
    for date in dates:
        for symbol in symbols:
            available=usable.get((date,symbol),[])
            # A disagreement is visible and not repaired by averaging or source cherry-picking.
            conflict=bool(available and any(abs(a[k]-available[0][k])>.0011 for a in available for k in ['high','low']))
            required.append(dict(date=date,symbol=symbol,valid_sources=len(available),source_conflict=conflict,
                covered=bool(available) and not conflict,
                reason='source_conflict' if conflict else 'valid' if available else 'no_valid_opening_window',
                source=available[0]['source'] if available else None,freq=available[0]['freq'] if available else None,
                high=available[0]['high'] if available else None,low=available[0]['low'] if available else None,
                volume=available[0]['volume'] if available else None))
    for name,rows in [('minute_inventory',inventory),('minute_source_checks',checks),('required_windows',required)]:
        pl.from_dicts(rows,infer_schema_length=None).write_csv(output/f'{name}.csv')
    gaps=[r for r in required if not r['covered']]
    pl.from_dicts(gaps,infer_schema_length=None).write_csv(output/'minute_gaps.csv')
    complete=[date for date in dates if all(r['covered'] for r in required if r['date']==date)]
    return dict(required_windows=len(required),covered_windows=len(required)-len(gaps),
        signal_dates=len(dates),complete_dates=len(complete),complete_dates_list=[str(d) for d in complete],
        full_period_execution_measurable=not gaps,delay_minutes=[1,3],
        delay_interpretation='both use full 09:30-09:35 worst-price window; not exact latency fills',
        gap_delivery='minute_gaps.csv for existing local minute recovery; no collection launched',
        continuous_delayed_nav='NOT_COMPUTED_missing_or_conflicting_windows' if gaps else 'coverage_ready_execution_still_required'),hashes


def refresh_registered(config,root):
    """Existing minute pipeline rechecks saved-data changes, with no collection or orders."""
    from quant.data.realtime_store import atomic_json
    from quant.execution.manual_session_service import instance_lock
    spec=tomllib.loads(config.read_text());source=Path(spec['source'])
    if spec['auto_trade'] is not False:raise ValueError('Require read-only research coverage')
    targets=pl.read_parquet(source/'dynamic_1/targets.parquet').filter(pl.col('execution_date')<=spec['end'])
    names=sorted(targets['symbol'].unique());paths=[config,source/'dynamic_1/targets.parquet',Path(__file__)]
    for s in names:
        paths.extend(Path('data/clean/bar_intraday').glob(f'freq=*m/source=*/symbol={s}/data.parquet'))
        paths.extend(Path('data/clean/futu_minute').glob(f'*/symbol={s}/year=*/data.parquet'))
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    key=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
    root.mkdir(parents=True,exist_ok=True)
    with instance_lock(root/'coverage.lock'):
        directory=root/key;checkpoint=directory/'summary.json'
        if checkpoint.exists():
            saved=json.loads(checkpoint.read_text())
            if all((directory/n).exists() and hashlib.sha256((directory/n).read_bytes()).hexdigest()==h
                   for n,h in saved['outputs'].items()):
                state={**saved,'reused':True};atomic_json(root/'latest.json',state);return state
        directory.mkdir(parents=True,exist_ok=True)
        result,_=inspect(directory,source,names,targets['execution_date'].unique().sort().to_list(),spec['end'])
        state=dict(state='complete',auto_trade=False,classification='RESEARCH_ONLY',fingerprint=key,
            gaps=str(directory/'minute_gaps.csv'),required_windows=str(directory/'required_windows.csv'),
            result=result,reused=False,inputs=hashes,
            outputs={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.glob('*.csv')})
        atomic_json(checkpoint,state);atomic_json(root/'latest.json',state)
        return state
