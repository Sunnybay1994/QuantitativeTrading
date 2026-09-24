"""Frozen 100k Q10/ETF joint replay using existing daily account and actual holdings."""
import argparse
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import tomllib

import polars as pl

from quant.data.factor_battery_inputs import read_battery_execution
from quant.data.stock_execution_inputs import stock_session_states
from quant.data.etf_paper_inputs import etf_session_states
from quant.portfolio.joint_allocation import allocate
from quant.research.classic_monthly_baseline import replay
from quant.research.run_s1_walk_forward import metrics


def run(output, config):
    spec=tomllib.loads(config.read_text(encoding='utf-8'))
    if spec['auto_trade'] is not False or spec['capital']!=100000:
        raise ValueError('Frozen manual-only 100k experiment required')
    output.mkdir(parents=True,exist_ok=False)
    (output/'config.toml').write_bytes(config.read_bytes())
    q=Path('artifacts/models/q10_sue_v2_turnover_budget_05_20260912_01')
    e=Path('artifacts/research/etf_allocation_attribution_20260922_03')
    manifest={str(config):hashlib.sha256(config.read_bytes()).hexdigest()}
    def read(p):
        manifest[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
        return pl.read_parquet(p)
    stock=read(q/'targets_budgeted.parquet').filter(pl.col('execution_date').is_between(spec['start'],spec['end']))
    dynamic=read(e/'dynamic_1/targets.parquet').filter(pl.col('execution_date').is_between(spec['start'],spec['end']))
    fixed=read(e/'fixed_1/targets.parquet').filter(pl.col('execution_date').is_between(spec['start'],spec['end']))
    columns=['as_of','execution_date','symbol','weight','strategy','strategy_version']
    stock,dynamic,fixed=[f.select(columns) for f in (stock,dynamic,fixed)]
    for targets in (dynamic,fixed):
        if not stock.select('as_of','execution_date').unique().sort('as_of').equals(targets.select('as_of','execution_date').unique().sort('as_of')):
            raise ValueError('Saved mechanism schedules differ; no implicit forward filling')
    if stock.filter(pl.col('as_of')>=pl.col('execution_date')).height:
        raise ValueError('Signal not before execution')
    etf_symbols=set(dynamic['symbol'])
    settings=tomllib.loads((q/'battery.toml').read_text(encoding='utf-8'))
    settings['portfolio']['initial_cash']=spec['capital']
    settings['share_exchanges']=tomllib.loads((q/'share_exchanges.toml').read_text(encoding='utf-8'))['share_exchanges']
    for p in (q/'battery.toml',q/'share_exchanges.toml',Path(settings['data']['refresh_config'])):
        manifest[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
    inputs=read_battery_execution(data_root=Path('data'),refresh_config=Path(settings['data']['refresh_config']),
        snapshot='factor_battery_20260911_v2',start=stock['as_of'].min(),end=spec['end'],
        symbols=sorted(set(stock['symbol'])),include_all_dividends=True)
    etf={name:read(e/f'{name}.parquet') for name in ['bars','calendar','dividends','instruments']}
    calendar=etf['calendar']
    sessions=calendar.filter((pl.col('market')=='SH')&pl.col('is_open')&pl.col('date').is_between(stock['as_of'].min(),spec['end']))['date'].sort().to_list()
    bars=pl.concat([inputs['bars'],etf['bars']],how='diagonal_relaxed').filter(pl.col('trade_date').is_between(sessions[0]-dt.timedelta(days=7),spec['end']))
    instruments=pl.concat([inputs['instruments'],etf['instruments']],how='diagonal_relaxed')
    dividends=pl.concat([inputs['dividends'].with_columns((pl.col('div_cash')*(1-settings['portfolio']['stock_dividend_withholding'])).alias('div_cash')),etf['dividends']],how='diagonal_relaxed')
    frozen=output/'inputs';frozen.mkdir()
    for name,frame in {**inputs,'joint_bars':bars,'joint_instruments':instruments,'joint_dividends':dividends,'etf_bars':etf['bars']}.items():
        p=frozen/f'{name}.parquet';frame.write_parquet(p);manifest[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
    for p in [Path(__file__),Path('src/quant/portfolio/joint_allocation.py'),Path('src/quant/research/classic_monthly_baseline.py')]:
        manifest[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    results=[]
    for cost in spec['cost_multipliers']:
        scenario=copy.deepcopy(settings)
        # Same stock costs as Q10, same ETF absolute-tick friction as frozen B16.
        scenario['costs']['etf'].update(slippage=0.,slippage_per_share=.001)
        for model in scenario['costs'].values():
            for field in ['commission_rate','commission_min','slippage','slippage_per_share']:
                if field in model: model[field]*=cost
        states=stock_session_states(bars=inputs['bars'],limits=inputs['limits'],suspensions=inputs['suspensions'],
            sessions=sessions,symbols=sorted(set(stock['symbol'])),execution_dates=sorted(stock['execution_date'].unique()),
            slippage=scenario['costs']['a_share']['slippage'])
        states.update(etf_session_states(etf['bars'],etf['dividends'],slippage=0.,slippage_per_share=.001*cost))
        for name,et,weight,cash in [('joint_dynamic',dynamic,.5,False),('joint_fixed',fixed,.5,False),
                                    ('stock_cash',fixed,.5,True),('q10_only',fixed,1.,True)]:
            folder=output/f'{name}_{cost:g}';folder.mkdir()
            targets=pl.concat([stock.with_columns((pl.col('weight')*weight).alias('weight')),
                              et.with_columns((pl.col('weight')*(1-weight)).alias('weight'))]).with_columns(
                                  pl.lit(name).alias('strategy'),pl.lit('joint_v1').alias('strategy_version'))
            constraints=[];records=[];exposure=[];account={}
            def transform(batch,state):
                desired=batch.with_columns(pl.when(pl.col('symbol').is_in(sorted(etf_symbols)))
                    .then(pl.col('weight')/(1-weight) if weight<1 else pl.col('weight'))
                    .otherwise(pl.col('weight')/weight).alias('weight'))
                return allocate(desired,state,stock_fraction=weight,etf_symbols=etf_symbols,cash_control=cash)
            def observe(date,state):
                mv={s:h['quantity']*h['mark_price'] for s,h in state['holdings'].items()}
                exposure.append(dict(date=date,stock_value=sum(v for s,v in mv.items() if s not in etf_symbols),
                                     etf_value=sum(v for s,v in mv.items() if s in etf_symbols),cash=state['cash']))
            nav,trades,rejects=replay(bars=bars,calendar=calendar,instruments=instruments,targets=targets,
                dividends=dividends,market_states=states,config=scenario,sessions=sessions,name=name,validate_once=True,
                account_state=account,target_constraints=transform,constraint_records=records,
                constraint_diagnostics=constraints,daily_observer=observe)
            nav=nav.filter(pl.col('date')>=spec['start'])
            for label,frame in [('nav',nav),('trades',trades),('rejections',rejects),('targets',pl.DataFrame(records)),('exposure',pl.DataFrame(exposure))]:
                frame.write_parquet(folder/f'{label}.parquet')
            (folder/'account.json').write_text(json.dumps(account,default=str),encoding='utf-8')
            # Each symbol/date has at most one net fill; one fee record per net order.
            duplicate=trades.select('date','symbol').is_duplicated().sum()
            if duplicate or nav.filter(pl.col('cash')<-.001).height:
                raise ValueError('Duplicate net fills or negative cash')
            if abs(float(trades['fee'].sum())-float(nav['cumulative_fees'][-1]))>1e-6:
                raise ValueError('Fee reconciliation failed')
            result=dict(rule=name,cost=cost,**metrics(nav,trades,initial_cash=spec['capital']),
                        rejected_orders=rejects.height,duplicate_net_fills=duplicate)
            results.append(result)
            (output/'progress.json').write_text(json.dumps(dict(completed=results),indent=2))
            print(json.dumps(dict(rule=name,cost=cost,status='complete',return_value=result['total_return'])),flush=True)
    (output/'summary.json').write_text(json.dumps(dict(results=results,classification='RESEARCH_ONLY',auto_trade=False),indent=2))
    from quant.research.joint_account_report import report
    report(output,spec)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--config',type=Path,default=Path('configs/research/joint_q10_etf_v1.toml'))
    a=p.parse_args();run(a.output,a.config)
