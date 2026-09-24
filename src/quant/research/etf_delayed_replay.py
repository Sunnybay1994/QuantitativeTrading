"""Continuous ETF ledger stress; stop at an actual unmeasurable net order."""
import argparse
import copy
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import tomllib

import polars as pl
from pandera.config import config_context

from quant.backtest.daily_account import advance
from quant.data.etf_paper_inputs import etf_session_states


def planned_orders(batch,state,close,lot):
    """Order quantities use only the completed signal close, including cash equity."""
    equity=state['nav'][-1]['equity'];as_of=batch['as_of'][0]
    if state['date']!=str(as_of):raise ValueError('Require actual signal-close account')
    desired=dict(batch.select('symbol','weight').iter_rows());rows=[]
    for symbol in sorted(set(desired)|set(state['holdings'])):
        quantity=math.floor(desired.get(symbol,0.)*equity/close[symbol]/lot[symbol])*lot[symbol]
        old=state['holdings'].get(symbol,{}).get('quantity',0);delta=quantity-old
        if delta:rows.append(dict(as_of=as_of,execution_date=batch['execution_date'][0],symbol=symbol,
            side='BUY' if delta>0 else 'SELL',quantity=abs(delta)))
    return pl.from_dicts(rows,schema={'as_of':pl.Date,'execution_date':pl.Date,'symbol':pl.String,'side':pl.String,'quantity':pl.Int64})


def run(measurement,output):
    spec=tomllib.loads((measurement/'config.toml').read_text());source=Path(spec['source'])
    output.mkdir(parents=True,exist_ok=False);hashes={}
    def read(p):hashes[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest();return pl.read_parquet(p)
    bars,calendar,instruments,dividends=[read(source/f'{n}.parquet') for n in ['bars','calendar','instruments','dividends']]
    policy=Path('configs/research/b16_cross_asset_inverse_volatility60_20260909.toml')
    base=tomllib.loads(policy.read_text());hashes[str(policy)]=hashlib.sha256(policy.read_bytes()).hexdigest()
    coverage_path=measurement/'required_windows.csv';hashes[str(coverage_path)]=hashlib.sha256(coverage_path.read_bytes()).hexdigest()
    windows={(r['date'],r['symbol']):r for r in pl.read_csv(coverage_path,try_parse_dates=True).to_dicts()}
    lots=dict(instruments.select('symbol','board_lot').iter_rows());results=[]
    for rule in ['dynamic','fixed']:
        targets=read(source/f'{rule}_1/targets.parquet').filter(pl.col('execution_date')<=spec['end'])
        sessions=calendar.filter((pl.col('market')=='SH')&pl.col('is_open')&
            pl.col('date').is_between(targets['as_of'].min(),spec['end']))['date'].sort().to_list()
        batches={d[0]:b for d,b in targets.partition_by('execution_date',as_dict=True).items()}
        for cost in spec['cost_multipliers']:
            folder=output/f'{rule}_{cost:g}';folder.mkdir()
            costs=copy.deepcopy(base['costs'])
            for key in ['commission_rate','commission_min','slippage','slippage_per_share']:costs['etf'][key]*=cost
            states=etf_session_states(bars,dividends,slippage=0.,slippage_per_share=.001*cost)
            state=dict(holdings={},cash=100000.,receivables=[],pending=[],nav=[])
            trades=[];rejects=[];plans=[];block=None
            for date in sessions:
                today=bars.filter(pl.col('trade_date')==date);batch=batches.get(date);orders=None
                if batch is not None:
                    close=dict(bars.filter(pl.col('trade_date')==batch['as_of'][0]).select('symbol','close').iter_rows())
                    orders=planned_orders(batch,state,close,lots);plans.extend(orders.to_dicts())
                    references={}
                    for order in orders.to_dicts():
                        w=windows.get((date,order['symbol']))
                        if w is None or not w['covered']:
                            block=dict(date=str(date),symbol=order['symbol'],side=order['side'],quantity=order['quantity'],
                                reason=w['reason'] if w else 'missing_window');break
                        p=w['high'] if order['side']=='BUY' else w['low']
                        daily=today.filter(pl.col('symbol')==order['symbol']).row(0,named=True)
                        if p<daily['low']-.0011 or p>daily['high']+.0011:
                            block=dict(date=str(date),symbol=order['symbol'],reason='minute_extreme_outside_daily_range');break
                        references[order['symbol']]=p
                    if block:break
                    today=today.with_columns(pl.Series('open',[references.get(r['symbol'],r['open']) for r in today.to_dicts()]))
                with config_context(validation_enabled=False):
                    state,result=advance(date=date,state=state,bars=today,calendar=calendar,instruments=instruments,
                        market_states=states,dividends=dividends,config=dict(paper=dict(name=rule,auto_trade=False,initial_cash=100000.),costs=costs),
                        scheduled_orders=orders)
                trades.append(result.trades);rejects.append(result.rejections)
            for label,frame in [('partial_nav' if block else 'nav',pl.from_dicts(state['nav'])),
                ('trades',pl.concat(trades)),('rejections',pl.concat(rejects)),('planned_orders',pl.from_dicts(plans))]:
                frame.write_parquet(folder/f'{label}.parquet')
            (folder/'account.json').write_text(json.dumps(state,default=str))
            results.append(dict(rule=rule,cost=cost,delay_minutes=[1,3],status='BLOCKED_INCOMPLETE_CONTINUOUS_REPLAY' if block else 'COMPLETE_PRICE_STRESS_ONLY',
                blocker=block,last_completed_session=state['date'],sessions_completed=len(state['nav'])-1,
                actual_orders=pl.concat(trades).height,no_partial_return_claim=True))
            print(json.dumps(results[-1]),flush=True)
    for p in [Path(__file__),measurement/'config.toml',Path('src/quant/backtest/daily_account.py'),Path('src/quant/backtest/daily_simulator.py')]:
        hashes[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
    summary=dict(auto_trade=False,classification='RESEARCH_ONLY',results=results,
        quantity_basis='signal-close targets, actual holdings and equity, frozen before execution extrema',
        price_stress='next 5m high BUY/low SELL plus original 0.5/1/2 fees and slippage; 1/3min share same bound',
        limitations=['Incomplete runs are not full-period NAV or profitability evidence.',
            'Price stress does not verify post-submission quote depth, capacity or real fills.',
            'Actual-order coverage is checked: missing windows for zero-net-order securities do not stop the account.'])
    (output/'summary.json').write_text(json.dumps(summary,indent=2));(output/'manifest.json').write_text(json.dumps(hashes,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--measurement',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();run(a.measurement,a.output)
