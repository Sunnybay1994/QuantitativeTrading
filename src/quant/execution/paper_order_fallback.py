"""Existing order rules on copied, verified same-day inputs; no collection or model refit."""
import argparse
import copy
import datetime as dt
import hashlib
import json
import shutil
import time
import tomllib
from dataclasses import fields
from pathlib import Path

import polars as pl

from quant.data.refresh import SHANGHAI
from quant.data.stock_paper_inputs import StockPaperInputs, read_stock_paper_calendar, read_stock_paper_inputs
from quant.execution import q10_paper
from quant.execution.paper_rehearsal import DEFAULT_CONFIG


def guard(deadline=None):
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError('Frozen order preparation exceeded its remaining capital-path budget')


def digest(path, deadline=None):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk:=stream.read(4*1024*1024):
            guard(deadline)
            value.update(chunk)
    return value.hexdigest()


def sources(data_root, config_path, state_path, forecast, date, config, deadline=None):
    """Exact files behind stock inputs and, where used, forward size controls."""
    refresh=Path(config['data']['refresh_config'])
    settings=tomllib.loads(refresh.read_text(encoding='utf-8'))
    result={config_path,refresh,state_path,Path(config['research']['assessment']),state_path.parent.parent/'controls.json',
            Path(config['model']['selection']),
            forecast/'summary.json',forecast/'predictions.parquet',forecast.parent/'summary.json'}
    result.update(data_root/f'clean/trade_calendar/market={m}/data.parquet' for m in ('SH','SZ'))
    start=config['data']['warmup_start']
    for year in range(start.year,date.year+1):
        result.update((data_root/'clean/tushare_bulk/snapshots'/settings['stock_snapshot']/
                      f'bar_1d/asset=stock/year={year}').glob('*.parquet'))
        result.update((data_root/'clean/tushare_daily_basic/snapshots'/settings['daily_basic_snapshot']/
                      f'year={year}').glob('*.parquet'))
    for folder in (data_root/'clean/tushare_incremental').glob('date=*'):
        if str(start)<=folder.name[5:]<=str(date):
            result.update(folder.glob('*.parquet'))
    result.update((data_root/f'clean/stock_paper_inputs/date={date}').glob('*'))
    if config['paper'].get('construction')=='b0.5_k50_size_on':
        result.add(data_root/'clean/stock_name_history/data.parquet')
        statistics=Path(config['paper']['statistics'])
        result.add(statistics/'battery.toml')
        result.update((statistics/f'inputs/{date.year}').glob('universe.parquet'))
        for summary in sorted((data_root/'clean/tushare_industry').glob('*/summary.json'),reverse=True):
            if json.loads(summary.read_text(encoding='utf-8')).get('with_current'):
                result.update([summary,summary.parent/'intervals.parquet']);break
    return {str(p):digest(p,deadline) for p in result if p.is_file()}


def freeze_account(*, data_root, config_path, account, end, output, forecast=None, as_month_end=False, deadline=None):
    guard(deadline)
    config=tomllib.loads(config_path.read_text(encoding='utf-8'))
    states=sorted(account.glob('????-??-??/state.json'))
    if not states:
        raise ValueError('Frozen fallback requires an existing account snapshot')
    state_path=states[-1]; state=json.loads(state_path.read_text(encoding='utf-8'))
    last=dt.date.fromisoformat(state['date'])
    calendar=read_stock_paper_calendar(data_root)
    sessions=sorted(calendar.filter(pl.col('is_open'))['date'].unique().to_list())
    following=next((day for day in sessions if day>end),None)
    if following is None or end not in sessions or end<last:
        raise ValueError('Frozen fallback requires the requested open session and following session')
    dates=[d for d in sessions if last<d<=end]
    if len(dates)>1:
        raise ValueError('Multiple missed account sessions require normal catch-up before fallback')
    candidates=([forecast] if forecast else [])+sorted(Path(config['model']['forecast_root']).glob('**/model/forecast'))
    forecast=next((p for p in candidates if p is not None and (p/'summary.json').is_file()
        and json.loads((p/'summary.json').read_text(encoding='utf-8')).get('as_of')==str(end)),None)
    if forecast is None:
        raise ValueError('No verified same-date frozen forecast; old-day reference is not ready')
    stamp=dt.datetime.fromisoformat(json.loads((forecast/'summary.json').read_text(encoding='utf-8'))['recorded_at'])
    if stamp.tzinfo is None or stamp>dt.datetime.now(SHANGHAI):
        raise ValueError('Frozen forecast was not available at the actual fallback clock')
    # Never call the stock input reader unless its provider capture is already present.
    for day in dates:
        folder=data_root/f'clean/stock_paper_inputs/date={day}'
        if not all((folder/f'{name}.parquet').is_file() for name in ('instruments','names','limits','suspensions','dividends')):
            raise ValueError(f'No frozen stock execution inputs for {day}; collection prohibited')
    before=sources(data_root,config_path,state_path,forecast,end,config,deadline)
    output.mkdir(parents=True,exist_ok=False)
    copied=output/'model/forecast';copied.mkdir(parents=True)
    for name in ('summary.json','predictions.parquet'):
        shutil.copy2(forecast/name,copied/name)
    shutil.copy2(forecast.parent/'summary.json',copied.parent/'summary.json')
    copied_stamp=dt.datetime.fromisoformat(json.loads((copied/'summary.json').read_text(encoding='utf-8'))['recorded_at'])
    if copied_stamp.tzinfo is None or copied_stamp>dt.datetime.now(SHANGHAI):
        raise ValueError('Copied forecast was not available at the actual fallback clock')
    scores=q10_paper.load_forecast(copied,end,Path(config['model']['selection']),following)
    calendar.write_parquet(output/'calendar.parquet')
    symbols=sorted(set(scores['symbol'])|set(state['holdings'])|
        {r['symbol'] for r in state['pending']}|{r['symbol'] for r in state.get('receivables',[])})
    saved={}
    for day in dates:
        guard(deadline)
        value=read_stock_paper_inputs(data_root,config,symbols,day)
        guard(deadline)
        saved[day]=value
        folder=output/str(day);folder.mkdir()
        for field in fields(StockPaperInputs):
            getattr(value,field.name).write_parquet(folder/f'{field.name}.parquet')
    transform=None
    if config['paper'].get('construction')=='b0.5_k50_size_on' and dates and (as_month_end or end.month!=following.month):
        from quant.research.run_constrained_portfolio import prepare_constrained_hook
        seed=copy.deepcopy(state);seed['date']=str(end)
        targets=q10_paper._ranked_selection(scores,seed,following,config['paper']['name'])
        transform,_,markets=prepare_constrained_hook(scores=scores.rename({'prediction':'score'}),
            targets=targets,statistics=Path(config['paper']['statistics']),policy=dict(config['paper']['size_on_policy']),
            score_column='score',minimum_signal_stocks=config['paper']['size_on_policy']['top_k'],data_root=data_root)
        markets.write_parquet(output/'size_markets.parquet')
    after=sources(data_root,config_path,state_path,forecast,end,config,deadline)
    if before!=after:
        raise ValueError('Order sources changed during freeze; no production account was advanced')
    (output/'sources.json').write_text(json.dumps(before,indent=2),encoding='utf-8')
    frozen={str(p.relative_to(output)):digest(p) for p in output.rglob('*') if p.is_file()}
    (output/'frozen_sha256.json').write_text(json.dumps(frozen,indent=2),encoding='utf-8')

    def read_frozen(_root,_config,wanted,day):
        guard(deadline)
        # Read copied parquet, not mutable provider or shared clean files.
        folder=output/str(day)
        frames={f.name:pl.read_parquet(folder/f'{f.name}.parquet') for f in fields(StockPaperInputs)}
        for name in ('bars','daily_basic','names','instruments','limits','suspensions','dividends'):
            frames[name]=frames[name].filter(pl.col('symbol').is_in(wanted))
        return StockPaperInputs(**frames)
    return dict(input_reader=read_frozen,calendar=pl.read_parquet(output/'calendar.parquet'),
                forecast=copied,size_transform=transform,
                _account_snapshot=dict(path=str(state_path),sha256=digest(state_path)))


def run(*, config=DEFAULT_CONFIG, end, output, account_writer=False, as_month_end=False, notify=False,
        budget_seconds=110):
    began=time.monotonic()
    if not 0 < budget_seconds <= 120:
        raise ValueError('Frozen orders require a positive budget of at most 120 seconds')
    deadline=began+budget_seconds
    settings=tomllib.loads(config.read_text(encoding='utf-8'))
    if settings.get('auto_trade') is not False:
        raise ValueError('Frozen order fallback requires auto_trade=false')
    output.mkdir(parents=True,exist_ok=False)
    result=dict(as_of=str(end),recorded_at=dt.datetime.now(SHANGHAI).isoformat(),
                mode='frozen_order_fallback',auto_trade=False,accounts={},rehearsal=as_month_end)
    prepared={}
    # Complete every source freeze before any production account changes.
    for name in ('q10','q10_shadow'):
        if name not in settings:continue
        spec=settings[name]
        if account_writer:
            result['accounts'][name]=dict(status='unavailable',reason='Account writer is still active; no concurrent ledger mutation')
            continue
        try:
            account=Path(spec['output'])
            if as_month_end and 'rehearsal' not in account.resolve().parts:
                raise ValueError('Forced month-end fallback requires isolated rehearsal account paths')
            frozen=freeze_account(data_root=Path(settings.get('data_root','data')),config_path=Path(spec['config']),
                account=account,end=end,output=output/'frozen'/name,as_month_end=as_month_end,deadline=deadline)
            prepared[name]=(spec,frozen)
        except Exception as exc:
            result['accounts'][name]=dict(status='unavailable',reason=f'{type(exc).__name__}: {exc}')
    for name,(spec,frozen) in prepared.items():
        try:
            guard(deadline)
            snapshot=frozen.pop('_account_snapshot')
            latest=sorted(Path(spec['output']).glob('????-??-??/state.json'))[-1]
            if latest!=Path(snapshot['path']) or digest(latest)!=snapshot['sha256']:
                raise ValueError('Account advanced during freeze; do not race its writer')
            value=q10_paper.run(config_path=Path(spec['config']),data_root=Path(settings.get('data_root','data')),
                output=Path(spec['output']),end=end,as_month_end=as_month_end,
                before_publish=lambda:guard(deadline),**frozen)
            if value['as_of']!=str(end):raise ValueError('Old account date is not order readiness')
            result['accounts'][name]=dict(status='complete',result=value)
            if notify and not as_month_end:
                from quant.execution.paper_order_chain import push_reference
                try:
                    result['accounts'][name]['notification']=push_reference(account=Path(spec['output']),summary=value)
                except Exception as exc:
                    result['accounts'][name]['notification_error']=f'{type(exc).__name__}: {exc}'
        except Exception as exc:
            result['accounts'][name]=dict(status='unavailable',reason=f'{type(exc).__name__}: {exc}')
    result['status']='complete' if result['accounts'] and all(x['status']=='complete' for x in result['accounts'].values()) else 'unavailable'
    result['elapsed_seconds']=time.monotonic()-began
    (output/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,default=DEFAULT_CONFIG)
    p.add_argument('--to',type=dt.date.fromisoformat,required=True)
    p.add_argument('--output',type=Path)
    p.add_argument('--account-writer',action='store_true')
    p.add_argument('--as-month-end',action='store_true')
    p.add_argument('--notify',action='store_true')
    p.add_argument('--budget-seconds',type=float,default=110)
    args=p.parse_args()
    output=args.output or Path('artifacts/paper/order_chain_fallback')/dt.datetime.now(SHANGHAI).strftime('%Y%m%dT%H%M%S_%f')
    result=run(config=args.config,end=args.to,output=output,account_writer=args.account_writer,as_month_end=args.as_month_end,notify=args.notify,budget_seconds=args.budget_seconds)
    print(json.dumps(result))
    raise SystemExit(0 if result['status']=='complete' else 2)


if __name__=='__main__':main()
