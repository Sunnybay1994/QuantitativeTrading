"""R1 actual-share quarterly portfolios, with annual checkpoints and proxy stress."""
import argparse
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import tomllib

import polars as pl

from quant.backtest.daily_account import advance
from quant.backtest.account_reconciliation import validate_nav,validate_registered_account
from quant.data.factor_battery_inputs import read_battery_execution
from quant.data.stock_execution_inputs import stock_session_states
from quant.portfolio.account_portfolio_v1 import Allocation
from quant.research.account_portfolio_etf_baselines import market_states
from quant.research.classic_monthly_baseline import replay
from quant.research.factor_cost_checkpoint import save_year,read_year


def run(*, config, panel, stock, output, resume=False):
    spec=tomllib.loads(config.read_text(encoding='utf-8'))
    if spec['auto_trade'] is not False or spec['capital_cny']!=300000:
        raise ValueError('Require preregistered 300k manual-only portfolio')
    if output.exists() and not resume:
        raise FileExistsError('Use explicit --resume for existing replay')
    output.mkdir(parents=True,exist_ok=True)
    paths=[config, panel/'summary.json',panel/'corporate_actions.toml',stock/'stock_leg_status.json',
           stock/'targets_budgeted.parquet',Path(__file__),Path('src/quant/portfolio/account_portfolio_v1.py'),
           Path('src/quant/backtest/daily_account.py'),Path('src/quant/backtest/daily_simulator.py'),
           Path('src/quant/backtest/account_reconciliation.py'),Path('src/quant/data/etf_corporate_actions.py')]
    for p in panel.glob('*.parquet'):
        paths.append(p)
    for cost in spec['cost_multipliers']:
        paths.append(stock/f'cost_{cost:g}/nav.parquet')
    manifest={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    frozen=output/'manifest.json'
    if frozen.exists() and json.loads(frozen.read_text(encoding='utf-8'))!=manifest:
        raise ValueError('Frozen portfolio input/code changed')
    frozen.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    (output/'config.toml').write_bytes(config.read_bytes())
    etf={p.stem:pl.read_parquet(p) for p in panel.glob('*.parquet')}
    events=tomllib.loads((panel/'corporate_actions.toml').read_text(encoding='utf-8'))['splits']
    source=Path(spec['stock_source'])
    base=tomllib.loads((source/'battery.toml').read_text(encoding='utf-8'))
    exchanges=tomllib.loads((source/'share_exchanges.toml').read_text(encoding='utf-8'))['share_exchanges']
    raw=pl.read_parquet(stock/'targets_budgeted.parquet')
    calendar=etf['calendar']
    all_days=sorted(calendar.filter(pl.col('is_open'))['date'].unique())
    following=dict(zip(all_days,all_days[1:]))
    receipt={'status':'running','auto_trade':False,'completed':[],'output':str(output)}
    def save():
        (output/'summary.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    save()
    try:
        for period in ('main','proxy_2015_2018'):
            proxy=period!='main'
            start=spec['pessimistic']['pre2019']['start'] if proxy else spec['start']
            end=spec['pessimistic']['pre2019']['end'] if proxy else spec['end']
            days=[d for d in all_days if start<=d<=end]
            previous=max(d for d in all_days if d<days[0])
            if proxy:
                signals=[previous]+[a for a,b in zip(days,days[1:]) if a.month!=b.month]
                plans=pl.from_dicts([dict(as_of=d,execution_date=following[d],symbol='510300.SH',
                    weight=1.,strategy='r1',strategy_version='1') for d in signals])
            else:
                plans=raw.filter(pl.col('execution_date').is_between(days[0],end)).with_columns(pl.lit('r1').alias('strategy'))
            for cost in spec['cost_multipliers']:
                settings=copy.deepcopy(base)
                settings['portfolio']['initial_cash']=300000.
                settings['share_exchanges']=exchanges
                settings['costs']['etf']={k:v for k,v in spec['costs']['etf'].items() if k!='stamp_tax'}
                settings['costs']['etf']['effective_from']=dt.date(2014,1,1)
                for model in settings['costs'].values():
                    for key in ('commission_rate','commission_min','slippage','slippage_per_share'):
                        if key in model:
                            model[key]*=cost
                prices=etf['economic_prices']
                wide=prices.pivot(on='symbol',index='trade_date',values='total_return_price').sort('trade_date')
                signals_returns=wide.select(pl.col('trade_date').alias('date'),
                    pl.col('512890.SH').pct_change().alias('dividend'),pl.col('511010.SH').pct_change().alias('treasury'))
                if proxy:
                    stock_returns=wide.select(pl.col('trade_date').alias('date'),pl.col('510300.SH').pct_change().alias('stock'))
                else:
                    n=pl.read_parquet(stock/f'cost_{cost:g}/nav.parquet')
                    first=n.filter(pl.col('market_value')>0)['date'].min()
                    stock_returns=n.filter(pl.col('date')>=first).select('date',pl.col('equity').pct_change().alias('stock'))
                returns=stock_returns.join(signals_returns,on='date',how='left')
                variants=spec['variants'] if proxy else [*spec['variants'],'treasury_only']
                for variant in variants:
                    root=output/period/variant/f'cost_{cost:g}'
                    root.mkdir(parents=True,exist_ok=True)
                    allocator=Allocation(variant=variant,spec=spec,returns=returns,etf_prices=None,proxy=proxy)
                    empty={'cash':300000.,'holdings':{},'receivables':[],'pending':[],'nav':[],
                           'inception_date':str(previous),'started_with_cash':True}
                    state,_=advance(date=previous,state=empty,bars=etf['bars'].head(0),calendar=calendar,
                        instruments=etf['instruments'],market_states={},dividends=etf['dividends'].head(0),
                        config={'paper':{'name':'r1','initial_cash':300000.,'auto_trade':False},'costs':settings['costs']})
                    chunks=[]
                    for year in range(days[0].year,end.year+1):
                        yd=[d for d in days if d.year==year]
                        folder=root/str(year)
                        if resume and folder.exists():
                            state,chunk=read_year(folder,dates=yd,previous=state)
                            allocation=json.loads((folder/'allocation_state.json').read_text())
                            allocator.reserved,allocator.initialized=allocation['reserved'],allocation['initialized']
                            chunks.append(chunk)
                            continue
                        targets=plans.filter(pl.col('execution_date').is_between(yd[0],yd[-1]))
                        if variant=='treasury_only':
                            targets=targets.select('as_of','execution_date','strategy','strategy_version').unique().with_columns(
                                pl.lit('511010.SH').alias('symbol'),pl.lit(1.).alias('weight')).select(plans.columns)
                        stock_symbols=(set(targets['symbol'])|set(state['holdings'])|
                            {r['symbol'] for r in state['receivables']})-set(etf['instruments']['symbol'])
                        if stock_symbols:
                            inputs=read_battery_execution(data_root=Path('data'),refresh_config=Path(base['data']['refresh_config']),
                                snapshot='factor_battery_20260911_v2',start=yd[0],end=yd[-1],
                                symbols=sorted(stock_symbols),include_all_dividends=True)
                            bars=pl.concat([inputs['bars'],etf['bars']],how='diagonal_relaxed')
                            instruments=pl.concat([inputs['instruments'],etf['instruments']],how='diagonal_relaxed').unique('symbol',keep='last')
                            div=inputs['dividends'].with_columns((pl.col('div_cash')*(1-base['portfolio']['stock_dividend_withholding'])).alias('div_cash'))
                            div=pl.concat([div,etf['dividends']],how='diagonal_relaxed')
                            states=stock_session_states(bars=inputs['bars'],limits=inputs['limits'],suspensions=inputs['suspensions'],
                                sessions=yd,symbols=sorted(stock_symbols),execution_dates=sorted(set(targets['execution_date'])),
                                slippage=settings['costs']['a_share']['slippage'])
                        else:
                            bars,instruments,div=etf['bars'],etf['instruments'],etf['dividends']
                            states={}
                        states.update(market_states(etf['bars'],etf['reference_prices'],events,cost))
                        records,diagnostics=[],[]
                        nav,trades,rejects=replay(bars=bars,calendar=calendar,instruments=instruments,targets=targets,
                            dividends=div,market_states=states,config=settings,sessions=yd,name='r1',validate_once=True,
                            account_state=state,target_constraints=None if variant=='treasury_only' else allocator,
                            constraint_records=records,constraint_diagnostics=diagnostics)
                        validate_nav(nav,label=str(folder))
                        save_year(folder,account=state,chunks=(nav,trades,rejects),target_records=records)
                        (folder/'allocation_state.json').write_text(json.dumps({'reserved':allocator.reserved,'initialized':allocator.initialized}))
                        (folder/'allocation.json').write_text(json.dumps(diagnostics,default=str,indent=2))
                        chunks.append((nav,trades,rejects))
                        print(json.dumps({'period':period,'variant':variant,'cost':cost,'year':year,'status':'saved'}),flush=True)
                    for label,index in [('nav',0),('trades',1),('rejections',2)]:
                        pl.concat([c[index] for c in chunks],how='diagonal_relaxed').write_parquet(root/f'{label}.parquet')
                    receipt['completed'].append({'period':period,'variant':variant,'cost_multiplier':cost,'path':str(root)})
                    save()
        receipt['status']='replayed'
        checks=validate_registered_account(output,receipt)
        (output/'return_reconciliation.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
        receipt['return_reconciliation']='return_reconciliation.json'
    except Exception as exc:
        receipt.update(status='failed',error=f'{type(exc).__name__}: {exc}')
        save()
        raise
    save()
    return receipt


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,default=Path('configs/research/account_portfolio_v1.toml'))
    p.add_argument('--panel',type=Path,required=True)
    p.add_argument('--stock',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--resume',action='store_true')
    args=p.parse_args()
    run(config=args.config,panel=args.panel,stock=args.stock,output=args.output,resume=args.resume)
