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


def run(*,config,output,resume=False):
    spec=tomllib.loads(config.read_text(encoding='utf-8'))
    if spec['auto_trade'] is not False or spec['capital_cny']!=300000:
        raise ValueError('Require the registered paper-only 300k Top15 experiment')
    if spec['execution'].get('quote_tick_cny')!=.01:
        raise ValueError('Require frozen legal A-share quote tick')
    if output.exists() and not resume:
        raise FileExistsError('Use explicit --resume for existing work')
    output.mkdir(parents=True,exist_ok=True)
    source,predictions=Path(spec['execution_source']),Path(spec['predictions'])
    sources=[config,source/'battery.toml',source/'share_exchanges.toml',predictions/'monthly_predictions.parquet',
        Path(__file__),Path('src/quant/execution/preposted_book.py'),Path('src/quant/portfolio/top15_limit.py'),
        Path('src/quant/backtest/daily_simulator.py'),Path('src/quant/backtest/daily_account.py')]
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
        for scenario,offset in [('limit_1pct',.01),('limit_3pct',.03),('open_full_fill',None)]:
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
                account_config={'paper':{'name':'top15_limit_v1','initial_cash':300000.,'auto_trade':False},'costs':settings['costs']}
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
                    symbols.update(o['symbol'] for o in book.orders if o['status']=='pending')
                    for event in exchanges:
                        if event['from_symbol'] in symbols:symbols.add(event['to_symbol'])
                    inputs=read_battery_execution(data_root=Path('data'),refresh_config=Path(base['data']['refresh_config']),
                        snapshot='factor_battery_20260911_v2',start=yd[0],end=yd[-1],symbols=sorted(symbols),include_all_dividends=True)
                    extra=read_daily_replay_limits(data_root=Path('data'),snapshot='limits_20260911',start=yd[0],end=yd[-1],symbols=sorted(symbols))
                    limits=pl.concat([inputs['limits'].select('symbol','trade_date','up_limit','down_limit'),extra.select('symbol','trade_date','up_limit','down_limit')]).unique(['symbol','trade_date'],keep='first',maintain_order=True)
                    states=stock_session_states(bars=inputs['bars'],limits=limits,suspensions=inputs['suspensions'],sessions=yd,symbols=sorted(symbols),
                        execution_dates=sorted(attempt_dates&set(yd)),slippage=settings['costs']['a_share']['slippage'])
                    dividends=inputs['dividends'].with_columns((pl.col('div_cash')*(1-base['portfolio']['stock_dividend_withholding'])).alias('div_cash'))
                    bars={k[0]:v for k,v in inputs['bars'].partition_by('trade_date',as_dict=True).items()}
                    navs,trades,rejects,audit=[],[],[],[]
                    for day in yd:
                        receipt['current']={'scenario':scenario,'cost':cost,'year':year,'date':str(day)}
                        prior=dt.date.fromisoformat(state['date'])
                        if prior in signal_days:
                            closes=dict(bars[prior].select('symbol','close').iter_rows())
                            for s,h in state['holdings'].items():closes.setdefault(s,h['mark_price'])
                            target,selected=select_targets(scores=score_days[prior],previous=selected,closes=closes,equity=state['nav'][-1]['equity'],execution_date=day)
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
                        missing=(set(orders['symbol'])|set(state['holdings']))-set(today['symbol'])
                        if missing:
                            prior_bars=inputs['bars'].filter(pl.col('symbol').is_in(sorted(missing)) & (pl.col('trade_date')<day))
                            prior_bars=prior_bars.sort('trade_date').unique('symbol',keep='last')
                            today=pl.concat([today,prior_bars])
                        with config_context(validation_enabled=False):
                            state,result=advance(date=day,state=state,bars=today,calendar=calendar,instruments=inputs['instruments'],
                                market_states=states,dividends=dividends,config=account_config,scheduled_orders=orders,preposted_limits=quoted_limits)
                        state.update(exchange_state)
                        for fill in result.trades.iter_rows(named=True):
                            o=meta[fill['symbol'],fill['side']]
                            opening=bars[day].filter(pl.col('symbol')==fill['symbol'])['open'].item()
                            quoted=fill['price']+(-1 if fill['side']=='BUY' else 1)*fill['slippage_cost']/fill['quantity']
                            if o['limit'] is not None and ((fill['side']=='BUY' and quoted>o['limit']+1e-7) or(fill['side']=='SELL' and quoted<o['limit']-1e-7)):
                                raise ValueError('Matched quote violates preposted limit')
                            audit.append({'date':day,'order_id':o['id'],'symbol':fill['symbol'],'side':fill['side'],'quantity':fill['quantity'],
                                'opening':opening,'matched_quote':quoted,'economic_price':fill['price'],'share_factor':o['share_factor'],
                                'signed_gap_to_open':(quoted-opening)*(1 if fill['side']=='BUY' else -1)*fill['quantity']})
                        book.settle(result.trades)
                        capture_exchange_holdings(date=day,state=state,events=exchanges)
                        navs.append(pl.from_dicts([state['nav'][-1]]).with_columns(pl.col('date').str.to_date()))
                        trades.append(result.trades);rejects.append(result.rejections)
                    chunk=(pl.concat(navs),pl.concat(trades),pl.concat(rejects),pl.from_dicts(audit) if audit else pl.DataFrame(schema={'date':pl.Date}))
                    BacktestNavSchema.validate(chunk[0].select(list(BacktestNavSchema.to_schema().columns)))
                    BacktestTradeSchema.validate(chunk[1]);BacktestRejectionSchema.validate(chunk[2])
                    folder.mkdir(exist_ok=False)
                    for kind,frame in zip(('nav','trades','rejections','audit'),chunk):frame.write_parquet(folder/f'{kind}.parquet')
                    (folder/'complete.json').write_text(json.dumps({'state':state,'selected':selected,'book':book.__dict__}))
                    parts.append(chunk)
                    print(json.dumps({'scenario':scenario,'cost':cost,'year':year,'status':'saved'}),flush=True)
                for index,kind in enumerate(('nav','trades','rejections','audit')):
                    pl.concat([c[index] for c in parts],how='diagonal_relaxed').write_parquet(root/f'{kind}.parquet')
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
