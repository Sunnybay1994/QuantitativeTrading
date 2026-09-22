"""Resume registered minute research after data refresh; no orders or parameter search."""
import argparse
import contextlib
import datetime as dt
import hashlib
import json
import tomllib
from pathlib import Path

import polars as pl

from quant.data.realtime_store import atomic_json
from quant.execution.manual_session_service import instance_lock
from quant.research import intraday_afternoon


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def inputs(config, data_root):
    raw=config.read_bytes()
    settings=tomllib.loads(raw.decode('utf-8'))
    if settings.get('auto_trade') is not False:
        raise ValueError('auto_trade must be false')
    files={'config.toml':raw}
    for frequency in ('1m','5m'):
        name=f"clean/bar_intraday/freq={frequency}/source={settings['source']}/symbol={settings['symbol']}/data.parquet"
        files['data/'+name]=(data_root/name).read_bytes()
    files['data/clean/trade_calendar/market=SH/data.parquet']=(data_root/'clean/trade_calendar/market=SH/data.parquet').read_bytes()
    files['replay.py']=Path(intraday_afternoon.__file__).read_bytes()
    files['pipeline.py']=Path(__file__).read_bytes()
    return files


def complete(checkpoint):
    if not checkpoint.exists():
        return None
    state=json.loads(checkpoint.read_text(encoding='utf-8'))
    if state.get('state')!='complete':
        return None
    for name,expected in state['outputs'].items():
        path=checkpoint.parent/name
        if not path.exists() or digest(path.read_bytes())!=expected:
            return None
    return state


def research_one(config, data_root, root):
    files=inputs(config,data_root)
    hashes={name:digest(raw) for name,raw in files.items()}
    key=digest(json.dumps(hashes,sort_keys=True).encode())
    directory=root/'runs'/config.stem/key
    checkpoint=directory/'checkpoint.json'
    previous=complete(checkpoint)
    if previous:
        for name,expected in hashes.items():
            frozen=directory/'snapshot'/name
            if not frozen.exists() or digest(frozen.read_bytes())!=expected:
                raise ValueError('Frozen input mismatch')
        return {**previous,'reused':True}
    directory.mkdir(parents=True,exist_ok=True)
    for name,raw in files.items():
        target=directory/'snapshot'/name
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():
            if digest(target.read_bytes())!=hashes[name]:
                raise ValueError('Frozen input mismatch')
        else:
            with target.open('xb') as stream:
                stream.write(raw)
    atomic_json(directory/'manifest.json',dict(inputs=hashes,fingerprint=key))
    # Incomplete attempts remain inspectable. Resume skips completed strategies,
    # and reruns only the interrupted small replay, never overwriting an attempt.
    number=1
    while (directory/f'attempt_{number:03d}').exists():
        number+=1
    attempt=directory/f'attempt_{number:03d}'
    atomic_json(checkpoint,dict(state='running',attempt=str(attempt),fingerprint=key))
    with (directory/f'attempt_{number:03d}.log').open('w',encoding='utf-8') as log,contextlib.redirect_stdout(log):
        result=intraday_afternoon.run(directory/'snapshot/config.toml',attempt,data_root=directory/'snapshot/data')
    quality=pl.read_csv(attempt/'daily_quality.csv')
    good=quality.filter(pl.all_horizontal('one_minute_valid','five_minute_valid','cross_frequency_matched'))
    last_input=quality['date'].max()
    good_dates=set(good['date'].to_list())
    calendar=pl.read_parquet(directory/'snapshot/data/clean/trade_calendar/market=SH/data.parquet')
    dates=calendar.filter(pl.col('is_open') & (pl.col('date')<=dt.date.fromisoformat(last_input)))['date'].sort().to_list()
    streak=0
    for date in reversed(dates):
        if str(date) not in good_dates:
            break
        streak+=1
    flags=['development_only','total_return_benchmark_not_validated']
    if result['missing_or_invalid_calendar_days']:
        flags.append('history_gaps_or_invalid_days')
    if result['exit_capacity_unverified']:
        flags.append('exit_capacity_unverified')
    if any(r['observed_day_return'] is not None and r['observed_day_return']<=0 for r in result['summaries'] if r['cost']==2):
        flags.append('nonpositive_stressed_return')
    if result['valid_days']==0:
        flags.append('no_valid_data')
    state=dict(state='complete',strategy=config.stem,fingerprint=key,reused=False,
               report=str(attempt/'report.md'),classification='RESEARCH_ONLY',auto_trade=False,
               latest_input_date=last_input,latest_valid_date=good['date'].max(),
               consecutive_valid_sessions=streak,valid_days=result['valid_days'],attention=flags,
               outputs={str(p.relative_to(directory)):digest(p.read_bytes()) for p in attempt.iterdir() if p.is_file()})
    state['results'] = result['summaries']
    state['periods'] = result.get('periods', [])
    if all(r.get('trades', 0)==0 for r in result['summaries']):
        state['attention'].append('no_trades')
    atomic_json(checkpoint,state)
    return state


def run(config):
    settings=tomllib.loads(config.read_text(encoding='utf-8'))
    if settings.get('auto_trade') is not False:
        raise ValueError('auto_trade must be false')
    root=Path(settings['output'])
    root.mkdir(parents=True,exist_ok=True)
    with instance_lock(root/'pipeline.lock'):
        state=dict(state='running',auto_trade=False,updated_at=dt.datetime.now().astimezone().isoformat(),strategies=[])
        atomic_json(root/'status.json',state)
        candidates = list(settings['strategies'])
        if settings.get('search'):
            from quant.research.minute_candidates import generate
            candidates.extend(generate(Path(settings['search']), root))
        for name in candidates:
            try:
                item=research_one(Path(name),Path(settings['data_root']),root)
            except Exception as exc:
                item=dict(strategy=Path(name).stem,state='failed',error=type(exc).__name__+': '+str(exc))
            # Freshness changes with the date even when input hashes do not.
            now=dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
            through=now.date() if now.hour>=16 else now.date()-dt.timedelta(days=1)
            if item['state']=='complete':
                cal=pl.read_parquet(Path(settings['data_root'])/'clean/trade_calendar/market=SH/data.parquet')
                latest=cal.filter(pl.col('is_open') & (pl.col('date')<=through))['date'].max()
                item['expected_completed_session']=str(latest)
                item['data_stale']=latest is None or item['latest_input_date']<str(latest)
            state['strategies'].append(item)
            atomic_json(root/'status.json',state)
        state['state']='failed' if any(r['state']=='failed' for r in state['strategies']) else 'complete'
        state['updated_at']=dt.datetime.now().astimezone().isoformat()
        atomic_json(root/'status.json',state)
        lines=['# 分钟研究自动流程','', 'complete 表示检查和开发回放完成，不代表策略可交易。所有结果为 RESEARCH_ONLY。','']
        rows=[]
        for item in state['strategies']:
            lines.append(f"- {item['strategy']}: {item['state']}; report={item.get('report','无')}; attention={item.get('attention',item.get('error'))}")
            rows.extend(dict(strategy=item['strategy'],report=item['report'],**result)
                        for result in item.get('results',[]))
        if rows:
            pl.DataFrame(rows,infer_schema_length=None).write_csv(root/'results.csv')
            lines.extend(['', '[全部候选、延迟及三档成本结果](results.csv)'])
        (root/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        return state


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',type=Path,default=Path('configs/research/minute_pipeline.toml'))
    args=parser.parse_args()
    result=run(args.config)
    print(json.dumps(result,ensure_ascii=False))
    return 1 if result['state']=='failed' else 0


if __name__=='__main__':
    raise SystemExit(main())
