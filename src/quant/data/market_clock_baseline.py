"""Bounded, prior-session-only same-clock amounts from existing market captures."""
import datetime as dt
import hashlib
import json
import math
import statistics
import tomllib
from collections import Counter
from pathlib import Path

import polars as pl

from quant.data.realtime_inputs import TZ
from quant.data.realtime_store import atomic_json
from quant.execution.manual_session_service import instance_lock

CONFIG = Path('configs/research/market_intraday_baseline_v1.toml')
SCHEMA = dict(symbol=pl.String, source=pl.String, provider_time=pl.String,
              received_at=pl.String, second=pl.Int64, minute=pl.String, amount=pl.Float64,
              snapshot=pl.String)


def load(path=CONFIG):
    cfg = tomllib.loads(path.read_text(encoding='utf-8'))
    if (cfg['auto_trade'] is not False or not 1 <= cfg['minimum_days'] <= cfg['lookback_sessions'] <= 60
            or not 1 <= cfg['max_snapshots_per_day'] <= 128
            or not 0 <= cfg['maximum_clock_gap_seconds'] < 60
            or cfg['source'] != 'tushare_sina' or cfg['amount_definition'] != 'cumulative_session_turnover_cny'):
        raise ValueError('Invalid descriptive baseline policy')
    return cfg


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def stamp(value):
    value = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(value)
    if value.tzinfo is None:
        raise ValueError('Naive timestamp')
    return value.astimezone(TZ)


def continuous(value):
    return dt.time(9,30) <= value.time() <= dt.time(11,30) or dt.time(13) <= value.time() < dt.time(15)


def second(value):
    return value.hour*3600+value.minute*60+value.second


def day_index(root, day, directories, cfg):
    """One cached parquet per immutable day fingerprint; never append to captured raw."""
    if len(directories) > cfg['max_snapshots_per_day']:
        return None, dict(date=str(day), status='snapshot_bound_exceeded', snapshots=len(directories))
    inputs, summaries = {}, {}
    for directory in directories:
        summary_path, quote_path = directory/'summary.json', directory/'quotes.json'
        if not summary_path.exists() or not quote_path.exists():
            continue
        summary = read(summary_path)
        ref = Path(summary.get('reference', 'missing'))
        for p in (summary_path,quote_path,ref):
            if p.is_file():
                stat=p.stat();inputs[str(p)]=[stat.st_size,stat.st_mtime_ns]
        summaries[directory] = summary
    key=hashlib.sha256(json.dumps(dict(inputs=inputs,policy=cfg,code=digest(Path(__file__))),sort_keys=True).encode()).hexdigest()
    cache=root/'baseline_cache'/str(day)/key
    cache.mkdir(parents=True,exist_ok=True)
    with instance_lock(cache/'build.lock'):
        receipt=cache/'summary.json';data=cache/'observations.parquet'
        if receipt.exists() and data.exists():
            saved=read(receipt)
            if digest(data)==saved['data_sha256']:
                return data,{**saved,'reused':True}
        rows, rejected, hashes = [], Counter(), {}
        for directory, summary in summaries.items():
            quote_path=directory/'quotes.json';ref=Path(summary.get('reference','missing'))
            try:
                completed=stamp(summary['completed_at'])
                if (summary.get('status')!='complete' or summary.get('auto_trade') is not False
                        or summary.get('scope')!=cfg['scope'] or completed.date()!=day
                        or summary.get('amount_definition',cfg['amount_definition'])!=cfg['amount_definition']):
                    raise ValueError('incomplete_or_different_scope')
                if quote_path.stat().st_size>cfg['max_quote_file_bytes']:
                    raise ValueError('quote_file_bound_exceeded')
                if not ref.is_file() or digest(ref)!=summary['reference_sha256']:
                    raise ValueError('historical_reference_missing_or_changed')
                reference=pl.read_parquet(ref)
                if reference['symbol'].is_duplicated().any() or reference['trade_date'].max()>=day:
                    raise ValueError('invalid_historical_reference')
                allowed=set(reference['symbol'])
                for p in (directory/'summary.json',quote_path,ref):hashes[str(p)]=digest(p)
                observations=read(quote_path)
                for q in observations:
                    try:
                        provider,received=stamp(q['provider_time']),stamp(q['received_at'])
                        amount=float(q['amount'])
                        if (provider.date()!=day or received.date()!=day or received>completed
                                or not 0 <= (received-provider).total_seconds() <= cfg['maximum_receipt_age_seconds']
                                or not continuous(provider)):
                            raise ValueError('invalid_historical_time')
                        if q['symbol'] not in allowed or q.get('source')!=cfg['source']:
                            raise ValueError('different_pool_or_provider')
                        if q.get('suspension') or not math.isfinite(amount) or amount<=0:
                            raise ValueError('invalid_cumulative_amount')
                        rows.append(dict(symbol=q['symbol'],source=q['source'],provider_time=provider.isoformat(),
                            received_at=received.isoformat(),second=second(provider),minute=provider.strftime('%H:%M'),
                            amount=amount,snapshot=str(directory)))
                    except (ValueError,KeyError,TypeError) as exc:
                        rejected[str(exc)]+=1
            except (ValueError,KeyError,TypeError) as exc:
                rejected[str(exc)]+=1
        if any(not Path(p).exists() or [Path(p).stat().st_size,Path(p).stat().st_mtime_ns]!=v for p,v in inputs.items()):
            raise ValueError('Historical inputs changed during read')
        frame=pl.from_dicts(rows,schema=SCHEMA).sort('received_at') if rows else pl.DataFrame(schema=SCHEMA)
        # Conflicting records at one provider observation are excluded, never averaged.
        keys=['symbol','source','provider_time']
        conflicts=frame.group_by(keys).agg(pl.col('amount').n_unique().alias('values')).filter(pl.col('values')>1)
        frame=frame.join(conflicts.select(keys),on=keys,how='anti').unique(keys,keep='first',maintain_order=True)
        rejected['conflicting_observations']=conflicts.height
        # Cumulative amount cannot go backwards in a stock/provider session.
        bad=frame.sort('provider_time').with_columns(pl.col('amount').diff().over('symbol','source').alias('_delta')).filter(pl.col('_delta')<0)
        bad_keys=bad.select('symbol','source').unique()
        frame=frame.join(bad_keys,on=['symbol','source'],how='anti')
        rejected['nonmonotonic_symbol_days']=bad_keys.height
        frame.write_parquet(data)
        result=dict(date=str(day),status='complete',snapshots=len(summaries),observations=frame.height,
            rejected=dict(rejected),source_hashes=hashes,data_sha256=digest(data),path=str(data),
            field=cfg['amount_definition'],source=cfg['source'],reused=False)
        atomic_json(receipt,result)
        return data,result


def enrich(quotes, reference, *, now, calendar, output, cfg=None, root=None):
    cfg=cfg or load();root=Path(root or cfg['snapshot_root']);now=stamp(now)
    output.mkdir(parents=True,exist_ok=True)
    sessions=sorted(set(calendar.filter(pl.col('is_open') & (pl.col('date')<now.date()))['date'].to_list()))[-cfg['lookback_sessions']:]
    directories={d:[] for d in sessions};observed_dates=set();ignored=Counter()
    for path in root.glob('????????T*'):
        if not path.is_dir():continue
        try:day=dt.datetime.strptime(path.name[:8],'%Y%m%d').date()
        except ValueError:continue
        observed_dates.add(str(day))
        if day in directories:directories[day].append(path)
        else:ignored['same_day_or_outside_lookback']+=1
    allowed=set(reference['symbol']);targets={}
    for q in quotes:
        try:
            if q.get('symbol') in allowed and stamp(q['provider_time']).date()==now.date():
                targets[q['symbol']]=q
        except (ValueError,KeyError,TypeError):pass
    records=[];receipts=[]
    for day,dirs in directories.items():
        if not dirs:continue
        path,receipt=day_index(root,day,sorted(dirs),cfg);receipts.append(receipt)
        if path is None:continue
        wanted={stamp(q['provider_time']).strftime('%H:%M') for q in targets.values()}
        records += pl.scan_parquet(path).filter(pl.col('minute').is_in(wanted)&pl.col('symbol').is_in(list(targets))).collect().to_dicts()
    groups={}
    for r in records:groups.setdefault((r['symbol'],r['source'],r['minute']),[]).append(r)
    enriched=[];details=[];reasons=Counter()
    for q in quotes:
        result={k:v for k,v in q.items() if not k.startswith('baseline_') and k!='past_same_time_amount'}
        try:provider=stamp(q['provider_time']);symbol=q['symbol']
        except (ValueError,KeyError,TypeError):
            result.update(baseline_valid_days=0,baseline_reason='invalid_current_timestamp')
            enriched.append(result);reasons['invalid_current_timestamp']+=1;continue
        key=(symbol,q.get('source'),provider.strftime('%H:%M'))
        selected={}
        if q['symbol'] in targets and provider.date()==now.date() and continuous(provider):
            for r in groups.get(key,[]):
                gap=second(provider)-r['second']
                if not 0<=gap<=cfg['maximum_clock_gap_seconds']:continue
                day=r['provider_time'][:10]
                if day not in selected or r['second']>selected[day]['second']:selected[day]=r
        count=len(selected)
        reason='ready' if count>=cfg['minimum_days'] else 'no_prior_same_clock_observation' if not count else 'insufficient_prior_days'
        if symbol not in allowed:reason='outside_current_reference'
        elif q.get('source')!=cfg['source']:reason='unsupported_provider'
        elif provider.date()!=now.date() or not continuous(provider):reason='outside_current_session'
        baseline=statistics.median(r['amount'] for r in selected.values()) if reason=='ready' else None
        result.update(baseline_valid_days=count,baseline_required_days=cfg['minimum_days'],baseline_reason=reason)
        if baseline is not None:
            result.update(past_same_time_amount=baseline,baseline_end_date=max(selected),baseline_clock=key[2],
                          baseline_source=q['source'],baseline_field=cfg['amount_definition'])
        gaps=[second(provider)-r['second'] for r in selected.values()]
        details.append(dict(symbol=q['symbol'],source=q.get('source'),clock=key[2],valid_days=count,
            required_days=cfg['minimum_days'],reason=reason,baseline=baseline,
            amount_ratio=float(q['amount'])/baseline if baseline and q.get('amount') is not None else None,
            max_clock_gap_seconds=max(gaps) if gaps else None,dates=','.join(sorted(selected))))
        reasons[reason]+=1;enriched.append(result)
    pl.from_dicts(details,infer_schema_length=None).write_csv(output/'coverage.csv') if details else (output/'coverage.csv').write_text('symbol,reason\n')
    summary=dict(status='complete',as_of=now.isoformat(),policy=cfg,observed_snapshot_dates=sorted(observed_dates),
        eligible_historical_dates=[r['date'] for r in receipts if r.get('observations',0)],
        reference_stocks=reference.height,matched_stocks=reasons['ready'],reasons=dict(reasons),ignored=dict(ignored),
        available_prior_sessions=len(sessions),day_receipts=receipts,
        aggregation='per-stock median of one same-provider earlier/equal clock record per prior day',
        classification_status='not_implemented',auto_trade=False)
    atomic_json(output/'summary.json',summary)
    return enriched,summary
