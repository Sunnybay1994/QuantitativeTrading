"""Actual-share R2 Top15/30 replay with three-session original-order retries."""
import argparse
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import tomllib

import polars as pl
from pandera.config import config_context

from quant.backtest.daily_account import advance,prepare_account_actions
from quant.backtest.share_exchanges import apply_share_exchanges,capture_exchange_holdings
from quant.data.factor_battery_inputs import read_battery_execution,read_daily_replay_limits
from quant.data.stock_paper_inputs import read_stock_paper_calendar
from quant.data.stock_execution_inputs import stock_session_states
from quant.domain import BacktestNavSchema,BacktestTradeSchema,BacktestRejectionSchema
from quant.execution.preposted_book import PrepostedBook
from quant.portfolio.top15_limit import targets as select_targets


def scenarios(spec):
    original=[('limit_1pct',.01),('limit_3pct',.03),('open_full_fill',None)]
    if not spec.get('r4'):
        if spec['scenarios']!=[name for name,_ in original]:
            raise ValueError('Original R2 replay requires its frozen three scenarios')
        return original
    r4=spec['r4']
    parent=Path(r4['parent_config'])
    if hashlib.sha256(parent.read_bytes()).hexdigest()!=r4['parent_config_sha256']:
        raise ValueError('R4 parent specification changed')
    if spec['cost_multipliers']!=[.5,1.,2.]:
        raise ValueError('R4 requires unchanged three cost levels')
    if r4['kind']=='pessimistic_fill':
        name='pessimistic_1pct'
        if r4['price_penetration_ticks']!=1 or r4['liquidity_notional_multiple']!=20:
            raise ValueError('Unregistered pessimistic matching parameters')
    elif r4['kind']=='new_name_budget':
        name='turnover7_1pct'
        if r4['maximum_new_names']!=7:
            raise ValueError('R4 fixes exactly seven subsequent new selected names')
    else:
        raise ValueError('Unknown R4 hypothesis')
    if spec['scenarios']!=[name]:
        raise ValueError('Run each R4 hypothesis once, not a parameter search')
    return [(name,.01)]


def run(*,config,output,resume=False):
    spec=tomllib.loads(config.read_text(encoding='utf-8'))
    if spec['auto_trade'] is not False or spec['capital_cny']!=300000:
        raise ValueError('Require the registered paper-only 300k Top15 experiment')
    if spec['execution'].get('quote_tick_cny')!=.01:
        raise ValueError('Require frozen legal A-share quote tick')
    experiments=scenarios(spec)
    r4=bool(spec.get('r4'))
    if output.exists() and not resume:
        raise FileExistsError('Use explicit --resume for existing work')
    output.mkdir(parents=True,exist_ok=True)
    source,predictions=Path(spec['execution_source']),Path(spec['predictions'])
    package=Path(__file__).resolve().parents[1]
    sources=[config,source/'battery.toml',source/'share_exchanges.toml',predictions/'monthly_predictions.parquet',
        Path(__file__),package/'execution/preposted_book.py',package/'portfolio/top15_limit.py',
        package/'backtest/daily_simulator.py',package/'backtest/daily_account.py']
    if r4:
        sources += [Path(spec['r4']['parent_config']),package/'backtest/top15_pessimistic.py']
        sources += [package/'backtest/account_reconciliation.py',package/'reporting/top15_r4.py']
        sources += [Path(spec['q10_control'])/f'budgeted/cost_{cost:g}/2018/account.json' for cost in spec['cost_multipliers']]
        sources += [Path(spec['r4']['baseline_run'])/variant/f'cost_{cost:g}/full_nav.parquet'
                    for variant in ('open_full_fill','limit_1pct') for cost in spec['cost_multipliers']]
    manifest={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    path=output/'manifest.json'
    if path.exists() and json.loads(path.read_text())!=manifest:
        raise ValueError('Frozen replay source changed')
    path.write_text(json.dumps(manifest,indent=2))
    (output/'config.toml').write_bytes(config.read_bytes())
    base=tomllib.loads((source/'battery.toml').read_text(encoding='utf-8'))
    exchanges=tomllib.loads((source/'share_exchanges.toml').read_text())['share_exchanges']
    calendar=read_stock_paper_calendar(Path('data'))
    all_days=sorted(calendar.filter(pl.col('is_open'))['date'].unique())
    following=dict(zip(all_days,all_days[1:]))
    scores=pl.read_parquet(predictions/'monthly_predictions.parquet').select('symbol','trade_date',pl.col('lightgbm').alias('prediction'))
    scores=scores.filter(pl.col('prediction').is_finite())
    signal_days={d for d in scores['trade_date'].unique() if d in following and
        spec['start']<=following[d]<=spec['end']}
    score_days={k[0]:v for k,v in scores.filter(pl.col('trade_date').is_in(sorted(signal_days))).partition_by('trade_date',as_dict=True).items()}
    ranked=scores.sort(['trade_date','prediction','symbol'],descending=[False,True,False]).group_by('trade_date',maintain_order=True).head(30)
    days=[d for d in all_days if spec['start']<=d<=spec['end']]
    attempt_dates=set()
    for signal in signal_days:
        index=all_days.index(following[signal])
        attempt_dates.update(all_days[index:index+3])
    receipt={'status':'running','auto_trade':False,'completed':[]}
    def save():
        (output/'summary.json').write_text(json.dumps(receipt,indent=2))
    save()
    try:
        for scenario,offset in experiments:
            for cost in spec['cost_multipliers']:
                root=output/scenario/f'cost_{cost:g}'
                root.mkdir(parents=True,exist_ok=True)
                state=json.loads((Path(spec['q10_control'])/f'budgeted/cost_{cost:g}/2018/account.json').read_text())['account']
                selected=[]
                book=PrepostedBook()
                settings=copy.deepcopy(base)
                for model in settings['costs'].values():
                    for field in ('commission_rate','commission_min','slippage','slippage_per_share'):
                        if field in model:model[field]*=cost
                account_config={'paper':{'name':spec['id'] if r4 else 'top15_limit_v1','initial_cash':300000.,'auto_trade':False},'costs':settings['costs']}
                parts=[]
                for year in range(days[0].year,days[-1].year+1):
                    yd=[d for d in days if d.year==year]
                    folder=root/str(year)
                    if resume and (folder/'complete.json').exists():
                        saved=json.loads((folder/'complete.json').read_text())
                        state,selected=saved['state'],saved['selected']
                        book.__dict__.update(saved['book'])
                        parts.append(tuple(pl.read_parquet(folder/f'{kind}.parquet') for kind in ('nav','trades','rejections','audit')))
                        continue
                    signals=[d for d in signal_days if yd[0]<=following[d]<=yd[-1]]
                    symbols=set(ranked.filter(pl.col('trade_date').is_in(signals))['symbol'])|set(state['holdings'])|{r['symbol'] for r in state['receivables']}
                    if r4:symbols.update(selected)
                    symbols.update(o['symbol'] for o in book.orders if o['status']=='pending')
                    for event in exchanges:
                        if event['from_symbol'] in symbols:symbols.add(event['to_symbol'])
                    inputs=read_battery_execution(data_root=Path('data'),refresh_config=Path(base['data']['refresh_config']),
                        snapshot='factor_battery_20260911_v2',start=yd[0],end=yd[-1],symbols=sorted(symbols),include_all_dividends=True)
                    extra=read_daily_replay_limits(data_root=Path('data'),snapshot='limits_20260911',start=yd[0],end=yd[-1],symbols=sorted(symbols))
                    if r4:
                        if inputs['instruments'].filter((pl.col('instrument_type')!='STOCK') | (pl.col('currency')!='CNY') | ~pl.col('market').is_in(['SH','SZ'])).height:
                            raise ValueError('R4 cent tick is only verified for Shanghai/Shenzhen CNY A-shares')
                        frozen=root/'execution_inputs'/str(year);frozen.mkdir(parents=True,exist_ok=False)
                        for kind,frame in inputs.items():frame.write_parquet(frozen/f'{kind}.parquet')
                        extra.write_parquet(frozen/'extra_limits.parquet')
                        (frozen/'sha256.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in frozen.glob('*.parquet')},indent=2))
                    limits=pl.concat([inputs['limits'].select('symbol','trade_date','up_limit','down_limit'),extra.select('symbol','trade_date','up_limit','down_limit')]).unique(['symbol','trade_date'],keep='first',maintain_order=True)
                    states=stock_session_states(bars=inputs['bars'],limits=limits,suspensions=inputs['suspensions'],sessions=yd,symbols=sorted(symbols),
                        execution_dates=sorted(attempt_dates&set(yd)),slippage=settings['costs']['a_share']['slippage'])
                    dividends=inputs['dividends'].with_columns((pl.col('div_cash')*(1-base['portfolio']['stock_dividend_withholding'])).alias('div_cash'))
                    bars={k[0]:v for k,v in inputs['bars'].partition_by('trade_date',as_dict=True).items()}
                    navs,trades,rejects,audit=[],[],[],[]
                    diagnostic_rows,selection_rows=[],[]
                    for day in yd:
                        receipt['current']={'scenario':scenario,'cost':cost,'year':year,'date':str(day)}
                        prior=dt.date.fromisoformat(state['date'])
                        if prior in signal_days:
                            closes=dict(bars[prior].select('symbol','close').iter_rows())
                            for s,h in state['holdings'].items():closes.setdefault(s,h['mark_price'])
                            previous=selected
                            selection_args=({'maximum_new_names':7} if scenario=='turnover7_1pct' and prior!=min(signal_days) else {})
                            target,selected=select_targets(scores=score_days[prior],previous=previous,closes=closes,equity=state['nav'][-1]['equity'],execution_date=day,**selection_args)
                            if r4:
                                selection_rows.append(dict(signal=str(prior),execution_date=str(day),initial_build=prior==min(signal_days),
                                    previous_selected=len(previous),selected=len(selected),new_selected=len(set(selected)-set(previous)),
                                    exited_selected=len(set(previous)-set(selected)),held_before=len(state['holdings']),
                                    new_symbols=','.join(sorted(set(selected)-set(previous))),exit_symbols=','.join(sorted(set(previous)-set(selected)))))
                            book.replace(signal=prior,targets=target,holdings=state['holdings'],equity=state['nav'][-1]['equity'],closes=closes,offset=offset)
                        book.apply_actions(day,inputs['dividends'])
                        if any(e['effective_date']==day and any(o['symbol']==e['from_symbol'] and o['status']=='pending' for o in book.orders) for e in exchanges):
                            raise ValueError('Pending exchange order requires explicit successor conversion')
                        apply_share_exchanges(date=day,state=state,events=exchanges,dividends=dividends)
                        exchange_state={k:state[k] for k in ('share_exchange_entitlements','share_exchange_history') if k in state}
                        delisted=set(inputs['instruments'].filter(pl.col('delist_date')<day)['symbol'])
                        for s in delisted:
                            state['holdings'].pop(s,None)
                            for o in book.orders:
                                if o['symbol']==s and o['status']=='pending':o['status']='delisted'
                        state['restricted_shares']=[r for r in state.get('restricted_shares',[]) if r['symbol'] not in delisted]
                        prepared=prepare_account_actions(date=day,state=state,calendar=calendar,dividends=dividends)
                        orders,quoted_limits=book.attempt(day,holdings=prepared['holdings'])
                        meta={(o['symbol'],o['side']):dict(o) for o in book.orders if o['status']=='pending'}
                        today=bars.get(day,inputs['bars'].head(0))
                        diagnostic_rejections=None
                        if scenario=='pessimistic_1pct':
                            from quant.backtest.top15_pessimistic import filter_orders
                            orders,diagnostic_rejections,details=filter_orders(orders=orders,limits=quoted_limits,
                                bars=today,date=day,strategy=spec['id'])
                            diagnostic_rows.extend([{**row,'order_id':meta[row['symbol'],row['side']]['id']} for row in details])
                        missing=(set(orders['symbol'])|set(state['holdings']))-set(today['symbol'])
                        if missing:
                            prior_bars=inputs['bars'].filter(pl.col('symbol').is_in(sorted(missing)) & (pl.col('trade_date')<day))
                            prior_bars=prior_bars.sort('trade_date').unique('symbol',keep='last')
                            today=pl.concat([today,prior_bars])
                        with config_context(validation_enabled=False):
                            state,result=advance(date=day,state=state,bars=today,calendar=calendar,instruments=inputs['instruments'],
                                market_states=states,dividends=dividends,config=account_config,scheduled_orders=orders,preposted_limits=quoted_limits)
                        state.update(exchange_state)
                        day_rejections=result.rejections
                        if diagnostic_rejections is not None and diagnostic_rejections.height:
                            day_rejections=pl.concat([day_rejections,diagnostic_rejections])
                        for fill in result.trades.iter_rows(named=True):
                            o=meta[fill['symbol'],fill['side']]
                            opening=bars[day].filter(pl.col('symbol')==fill['symbol'])['open'].item()
                            quoted=fill['price']+(-1 if fill['side']=='BUY' else 1)*fill['slippage_cost']/fill['quantity']
                            if o['limit'] is not None and ((fill['side']=='BUY' and quoted>o['limit']+1e-7) or(fill['side']=='SELL' and quoted<o['limit']-1e-7)):
                                raise ValueError('Matched quote violates preposted limit')
                            audit.append({'date':day,'order_id':o['id'],'symbol':fill['symbol'],'side':fill['side'],'quantity':fill['quantity'],
                                'opening':opening,'matched_quote':quoted,'economic_price':fill['price'],'share_factor':o['share_factor'],
                                'signed_gap_to_open':(quoted-opening)*(1 if fill['side']=='BUY' else -1)*fill['quantity'],
                                **({'new_position_buy':fill['side']=='BUY' and prepared['holdings'].get(fill['symbol'],{}).get('quantity',0)==0} if r4 else {})})
                        book.settle(result.trades)
                        capture_exchange_holdings(date=day,state=state,events=exchanges)
                        navs.append(pl.from_dicts([state['nav'][-1]]).with_columns(pl.col('date').str.to_date()))
                        trades.append(result.trades);rejects.append(day_rejections)
                    chunk=(pl.concat(navs),pl.concat(trades),pl.concat(rejects),pl.from_dicts(audit) if audit else pl.DataFrame(schema={'date':pl.Date}))
                    BacktestNavSchema.validate(chunk[0].select(list(BacktestNavSchema.to_schema().columns)))
                    BacktestTradeSchema.validate(chunk[1]);BacktestRejectionSchema.validate(chunk[2])
                    folder.mkdir(exist_ok=False)
                    for kind,frame in zip(('nav','trades','rejections','audit'),chunk):frame.write_parquet(folder/f'{kind}.parquet')
                    if r4:
                        pl.from_dicts(selection_rows).write_parquet(folder/'selection.parquet')
                        (pl.from_dicts(diagnostic_rows,infer_schema_length=None) if diagnostic_rows else pl.DataFrame(schema={'date':pl.Date})).write_parquet(folder/'diagnostic_attempts.parquet')
                    (folder/'complete.json').write_text(json.dumps({'state':state,'selected':selected,'book':book.__dict__}))
                    parts.append(chunk)
                    print(json.dumps({'scenario':scenario,'cost':cost,'year':year,'status':'saved'}),flush=True)
                for index,kind in enumerate(('nav','trades','rejections','audit')):
                    pl.concat([c[index] for c in parts],how='diagonal_relaxed').write_parquet(root/f'{kind}.parquet')
                if r4:
                    for kind in ['selection','diagnostic_attempts']:
                        frames=[pl.read_parquet(root/str(year)/f'{kind}.parquet') for year in range(days[0].year,days[-1].year+1)]
                        pl.concat(frames,how='diagonal_relaxed').write_parquet(root/f'{kind}.parquet')
                (root/'orders.json').write_text(json.dumps(book.history+book.orders))
                receipt['completed'].append({'variant':scenario,'cost_multiplier':cost,'path':str(root)})
                save()
        receipt['status']='replayed'
    except Exception as exc:
        receipt.update(status='failed',error=f'{type(exc).__name__}: {exc}')
        save();raise
    save()
    return receipt


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,default=Path('configs/research/top15_limit_v1.toml'))
    p.add_argument('--output',type=Path,required=True);p.add_argument('--resume',action='store_true')
    a=p.parse_args();run(config=a.config,output=a.output,resume=a.resume)
