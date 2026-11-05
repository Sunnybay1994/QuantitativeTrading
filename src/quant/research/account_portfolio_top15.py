"""R1 conditional Top15 stock-leg control, with a single actual-cash account."""
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
from quant.data.stock_execution_inputs import stock_session_states
from quant.domain import BacktestNavSchema,BacktestTradeSchema,BacktestRejectionSchema
from quant.execution.preposted_book import PrepostedBook
from quant.portfolio.account_portfolio_top15 import Top15Allocation,joint_orders
from quant.research.account_portfolio_etf_baselines import market_states


def run(*,config,panel,output,resume=False):
    spec=tomllib.loads(config.read_text(encoding='utf-8'))
    if spec['auto_trade'] is not False or spec['capital_cny']!=300000 or spec['stock_limit_offset']!=.01:
        raise ValueError('Require registered 300k manual-only 1% primary control')
    if spec['fixed_weights']!=[.4,.3,.3] or spec['variants']!=['fixed_40_30_30','inverse_volatility60']:
        raise ValueError('Do not change the R1 allocation hypotheses')
    if output.exists() and not resume:
        raise FileExistsError('Explicit resume required')
    output.mkdir(parents=True,exist_ok=True)
    baseline,control,source=Path(spec['r1_baseline']),Path(spec['top15_replay']),Path(spec['stock_source'])
    baseline_receipt=json.loads((baseline/'summary.json').read_text(encoding='utf-8'))
    control_receipt=json.loads((control/'summary.json').read_text(encoding='utf-8'))
    if baseline_receipt['status']!='replayed' or control_receipt['status']!='replayed':
        raise ValueError('Require completed original R1 and R2 controls')
    reuse=[r for r in baseline_receipt['completed'] if r['period']!='main' or r['variant']=='treasury_only']
    paths=[config,panel/'summary.json',panel/'corporate_actions.toml',source/'battery.toml',
        source/'share_exchanges.toml',Path(spec['stock_selection_config']),
        Path(spec['predictions'])/'monthly_predictions.parquet',Path(__file__),
        Path('src/quant/portfolio/account_portfolio_top15.py'),Path('src/quant/portfolio/account_portfolio_v1.py'),
        Path('src/quant/portfolio/top15_limit.py'),Path('src/quant/execution/preposted_book.py'),
        Path('src/quant/backtest/daily_account.py'),Path('src/quant/backtest/daily_simulator.py'),
        baseline/'summary.json',control/'summary.json']
    paths.extend(panel.glob('*.parquet'))
    for entry in reuse:
        paths.extend(Path(entry['path'])/f'{kind}.parquet' for kind in ('nav','trades','rejections'))
    for cost in spec['cost_multipliers']:
        paths.extend(control/'limit_1pct'/f'cost_{cost:g}'/f'{kind}.parquet' for kind in ('nav','trades'))
    manifest={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    frozen=output/'manifest.json'
    if frozen.exists() and json.loads(frozen.read_text(encoding='utf-8'))!=manifest:
        raise ValueError('Frozen joint-account inputs changed')
    frozen.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    (output/'config.toml').write_bytes(config.read_bytes())
    etf={p.stem:pl.read_parquet(p) for p in panel.glob('*.parquet')}
    events=tomllib.loads((panel/'corporate_actions.toml').read_text(encoding='utf-8'))['splits']
    base=tomllib.loads((source/'battery.toml').read_text(encoding='utf-8'))
    exchanges=tomllib.loads((source/'share_exchanges.toml').read_text(encoding='utf-8'))['share_exchanges']
    calendar=etf['calendar']
    all_days=sorted(calendar.filter(pl.col('is_open'))['date'].unique())
    following=dict(zip(all_days,all_days[1:]))
    days=[d for d in all_days if spec['start']<=d<=spec['end']]
    before=max(d for d in all_days if d<days[0])
    scores=pl.read_parquet(Path(spec['predictions'])/'monthly_predictions.parquet').select(
        'symbol','trade_date',pl.col('lightgbm').alias('prediction')).filter(pl.col('prediction').is_finite())
    signals={d for d in scores['trade_date'].unique() if d in following and days[0]<=following[d]<=days[-1]}
    score_days={k[0]:v for k,v in scores.filter(pl.col('trade_date').is_in(sorted(signals))).partition_by('trade_date',as_dict=True).items()}
    ranked=scores.sort(['trade_date','prediction','symbol'],descending=[False,True,False]).group_by('trade_date',maintain_order=True).head(30)
    attempts=set()
    for signal in signals:
        index=all_days.index(following[signal]);attempts.update(all_days[index:index+3])
    receipt={'status':'running','auto_trade':False,'completed':reuse,
        'reused_controls':'Original R1 treasury and pre2019 proxy; paths and hashes preserved',
        'stock_rule':spec['stock_rule']}
    def save():
        temporary=output/'summary.json.tmp'
        temporary.write_text(json.dumps(receipt,indent=2),encoding='utf-8')
        temporary.replace(output/'summary.json')
    save()
    try:
        for cost in spec['cost_multipliers']:
            settings=copy.deepcopy(base)
            settings['costs']['etf']={k:v for k,v in spec['costs']['etf'].items() if k!='stamp_tax'}
            settings['costs']['etf']['effective_from']=dt.date(2014,1,1)
            for model in settings['costs'].values():
                for key in ('commission_rate','commission_min','slippage','slippage_per_share'):
                    if key in model:model[key]*=cost
            account_config={'paper':{'name':spec['id'],'initial_cash':300000.,'auto_trade':False},'costs':settings['costs']}
            wide=etf['economic_prices'].pivot(on='symbol',index='trade_date',values='total_return_price').sort('trade_date')
            etf_returns=wide.select(pl.col('trade_date').alias('date'),pl.col('512890.SH').pct_change().alias('dividend'),
                pl.col('511010.SH').pct_change().alias('treasury'))
            returns=pl.read_parquet(control/'limit_1pct'/f'cost_{cost:g}'/'nav.parquet').select(
                'date',pl.col('equity').pct_change().alias('stock')).join(etf_returns,on='date',how='left')
            for variant in spec['variants']:
                root=output/'main'/variant/f'cost_{cost:g}';root.mkdir(parents=True,exist_ok=True)
                allocator=Top15Allocation(variant=variant,spec=spec,returns=returns,etf_prices=None)
                state,_=advance(date=before,state={'cash':300000.,'holdings':{},'receivables':[],'pending':[],'nav':[],
                    'inception_date':str(before),'started_with_cash':True},bars=etf['bars'].head(0),calendar=calendar,
                    instruments=etf['instruments'],market_states={},dividends=etf['dividends'].head(0),config=account_config)
                book,selected,parts=PrepostedBook(),[],[]
                for year in range(days[0].year,days[-1].year+1):
                    yd=[d for d in days if d.year==year];folder=root/str(year)
                    if resume and (folder/'complete.json').exists():
                        saved=json.loads((folder/'complete.json').read_text(encoding='utf-8'))
                        state,selected=saved['state'],saved['selected'];book.__dict__.update(saved['book'])
                        allocator.reserved,allocator.initialized=saved['reserved'],saved['initialized']
                        parts.append(tuple(pl.read_parquet(folder/f'{kind}.parquet') for kind in ('nav','trades','rejections')))
                        continue
                    yearly_signals=[s for s in signals if yd[0]<=following[s]<=yd[-1]]
                    symbols=set(ranked.filter(pl.col('trade_date').is_in(yearly_signals))['symbol'])|set(selected)|set(state['holdings'])
                    symbols.update(r['symbol'] for r in state['receivables'])
                    symbols-=set(etf['instruments']['symbol'])
                    for event in exchanges:
                        if event['from_symbol'] in symbols:symbols.add(event['to_symbol'])
                    inputs=read_battery_execution(data_root=Path('data'),refresh_config=Path(base['data']['refresh_config']),
                        snapshot='factor_battery_20260911_v2',start=yd[0],end=yd[-1],symbols=sorted(symbols),include_all_dividends=True)
                    extra=read_daily_replay_limits(data_root=Path('data'),snapshot='limits_20260911',start=yd[0],end=yd[-1],symbols=sorted(symbols))
                    limits=pl.concat([inputs['limits'].select('symbol','trade_date','up_limit','down_limit'),extra.select('symbol','trade_date','up_limit','down_limit')]).unique(['symbol','trade_date'],keep='first',maintain_order=True)
                    states=stock_session_states(bars=inputs['bars'],limits=limits,suspensions=inputs['suspensions'],sessions=yd,
                        symbols=sorted(symbols),execution_dates=sorted(attempts&set(yd)),slippage=settings['costs']['a_share']['slippage'])
                    states.update(market_states(etf['bars'],etf['reference_prices'],events,cost))
                    dividends=pl.concat([inputs['dividends'].with_columns((pl.col('div_cash')*(1-base['portfolio']['stock_dividend_withholding'])).alias('div_cash')),etf['dividends']],how='diagonal_relaxed')
                    combined=pl.concat([inputs['bars'],etf['bars']],how='diagonal_relaxed')
                    bars={k[0]:v for k,v in combined.partition_by('trade_date',as_dict=True).items()}
                    instruments=pl.concat([inputs['instruments'],etf['instruments']],how='diagonal_relaxed').unique('symbol',keep='last')
                    navs,execution_navs,trades,rejects,allocation,audit=[],[],[],[],[],[]
                    for day in yd:
                        receipt['current']={'variant':variant,'cost':cost,'year':year,'date':str(day)}
                        prior=dt.date.fromisoformat(state['date'])
                        etf_orders=pl.DataFrame(schema={'as_of':pl.String,'execution_date':pl.String,'symbol':pl.String,'side':pl.String,'quantity':pl.Int64})
                        if prior in signals:
                            closes=dict(bars[prior].select('symbol','close').iter_rows())
                            for s,h in state['holdings'].items():closes.setdefault(s,h['mark_price'])
                            target,selected,etf_orders,info=allocator.plan(scores=score_days[prior],previous=selected,
                                closes=closes,state=state,execution_date=day)
                            allocation.append(info)
                            stock_holdings={s:h for s,h in state['holdings'].items() if s not in allocator.etfs}
                            book.replace(signal=prior,targets=target,holdings=stock_holdings,
                                equity=info['stock_equity_before_allocation'],closes=closes,offset=.01)
                        book.apply_actions(day,inputs['dividends'])
                        if any(e['effective_date']==day and any(o['symbol']==e['from_symbol'] and o['status']=='pending' for o in book.orders) for e in exchanges):
                            raise ValueError('Pending exchange order requires explicit successor mapping')
                        apply_share_exchanges(date=day,state=state,events=exchanges,dividends=dividends)
                        exchange_state={k:state[k] for k in ('share_exchange_entitlements','share_exchange_history') if k in state}
                        delisted=set(inputs['instruments'].filter(pl.col('delist_date')<day)['symbol'])
                        for s in delisted:
                            state['holdings'].pop(s,None)
                            for order in book.orders:
                                if order['symbol']==s and order['status']=='pending':order['status']='delisted'
                        state['restricted_shares']=[r for r in state.get('restricted_shares',[]) if r['symbol'] not in delisted]
                        prepared=prepare_account_actions(date=day,state=state,calendar=calendar,dividends=dividends)
                        stock_orders,quoted=book.attempt(day,holdings=prepared['holdings'])
                        orders,quoted=joint_orders(stock_orders,quoted,etf_orders)
                        today=bars.get(day,combined.head(0))
                        missing=(set(orders['symbol'])|set(state['holdings']))-set(today['symbol'])
                        if missing:
                            previous_bars=combined.filter(pl.col('symbol').is_in(sorted(missing))&(pl.col('trade_date')<day)).sort('trade_date').unique('symbol',keep='last')
                            today=pl.concat([today,previous_bars])
                        with config_context(validation_enabled=False):
                            state,result=advance(date=day,state=state,bars=today,calendar=calendar,instruments=instruments,
                                market_states=states,dividends=dividends,config=account_config,scheduled_orders=orders,preposted_limits=quoted)
                        state.update(exchange_state)
                        stock_fills=result.trades.filter(~pl.col('symbol').is_in(allocator.etfs))
                        for fill in stock_fills.iter_rows(named=True):
                            matched=fill['price']+(-1 if fill['side']=='BUY' else 1)*fill['slippage_cost']/fill['quantity']
                            bound=quoted[fill['symbol'],fill['side']]
                            if (fill['side']=='BUY' and matched>bound+1e-7) or (fill['side']=='SELL' and matched<bound-1e-7):
                                raise ValueError('Stock matched quote outside original bound')
                            audit.append({'date':str(day),'symbol':fill['symbol'],'side':fill['side'],
                                'quantity':fill['quantity'],'matched_quote':matched,'limit':bound})
                        book.settle(stock_fills)
                        capture_exchange_holdings(date=day,state=state,events=exchanges)
                        navs.append(pl.from_dicts([state['nav'][-1]]).with_columns(pl.col('date').str.to_date()))
                        execution_navs.append(result.nav)
                        trades.append(result.trades);rejects.append(result.rejections)
                    chunk=(pl.concat(navs,how='diagonal_relaxed'),pl.concat(trades),pl.concat(rejects))
                    # Same distinction as classic_monthly_baseline: execution NAV
                    # excludes receivables; the complete ledger retains them.
                    BacktestNavSchema.validate(pl.concat(execution_navs,how='vertical_relaxed'))
                    if chunk[0]['date'].to_list()!=yd or chunk[0].filter(
                            (pl.col('equity')-pl.col('cash')-pl.col('market_value')-pl.col('receivable')).abs()
                            >pl.col('equity').abs().clip(lower_bound=1.)*1e-9).height:
                        raise ValueError('Complete account date grid or receivable reconciliation failed')
                    BacktestTradeSchema.validate(chunk[1]);BacktestRejectionSchema.validate(chunk[2])
                    folder.mkdir(exist_ok=False)
                    for kind,frame in zip(('nav','trades','rejections'),chunk):frame.write_parquet(folder/f'{kind}.parquet')
                    (folder/'allocation.json').write_text(json.dumps(allocation,indent=2),encoding='utf-8')
                    (folder/'limit_audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
                    (folder/'complete.json').write_text(json.dumps({'state':state,'selected':selected,'book':book.__dict__,
                        'reserved':allocator.reserved,'initialized':allocator.initialized}),encoding='utf-8')
                    parts.append(chunk)
                    print(json.dumps({'variant':variant,'cost':cost,'year':year,'status':'saved'}),flush=True)
                for index,kind in enumerate(('nav','trades','rejections')):
                    pl.concat([c[index] for c in parts],how='diagonal_relaxed').write_parquet(root/f'{kind}.parquet')
                (root/'orders.json').write_text(json.dumps(book.history+book.orders),encoding='utf-8')
                receipt['completed'].append({'period':'main','variant':variant,'cost_multiplier':cost,'path':str(root)})
                save()
        receipt['status']='replayed'
    except Exception as exc:
        receipt.update(status='failed',error=f'{type(exc).__name__}: {exc}');save();raise
    save()
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=Path('configs/research/account_portfolio_top15_v1.toml'))
    parser.add_argument('--panel',type=Path,default=Path('data/clean/account_portfolio_v1_20261104_04'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args();run(config=args.config,panel=args.panel,output=args.output,resume=args.resume)
