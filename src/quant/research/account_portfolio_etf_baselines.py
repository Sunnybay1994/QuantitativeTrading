"""Standalone ETF ledger baselines needed before the R1 account portfolio replay."""
import argparse
import copy
import datetime as dt
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import tomllib

import polars as pl

from quant.backtest.rules import DailyMarketState
from quant.research.classic_monthly_baseline import replay


def market_states(bars, references, splits, multiplier):
    joined = bars.join(references, on=['symbol','trade_date'], how='left')
    states = {}
    for row in joined.iter_rows(named=True):
        ref = Decimal(str(row['pre_close']))
        if not ref.is_finite() or ref <= 0:
            raise ValueError('Missing daily ETF exchange reference')
        upper = float((ref*Decimal('1.1')).quantize(Decimal('.001'),rounding=ROUND_HALF_UP))
        lower = float((ref*Decimal('.9')).quantize(Decimal('.001'),rounding=ROUND_HALF_UP))
        states[row['trade_date'],row['symbol']] = DailyMarketState(
            suspended=row['volume'] <= 0,
            at_upper_limit=row['open']+.001*multiplier >= upper-1e-9,
            at_lower_limit=row['open']-.001*multiplier <= lower+1e-9)
    for event in splits:
        for date in event['suspended_dates']:
            states[date,event['symbol']] = DailyMarketState(suspended=True)
    return states


def run(*, panel: Path, config: Path, output: Path):
    spec = tomllib.loads(config.read_text(encoding='utf-8'))
    if spec['auto_trade'] is not False or spec['capital_cny'] != 300000:
        raise ValueError('Require registered paper-only capital')
    output.mkdir(parents=True, exist_ok=False)
    (output/'config.toml').write_bytes(config.read_bytes())
    metadata = json.loads((panel/'summary.json').read_text(encoding='utf-8'))
    inputs = {}
    for key, info in metadata['products'].items():
        path = panel/f'{key}.parquet'
        if hashlib.sha256(path.read_bytes()).hexdigest() != info['sha256']:
            raise ValueError(f'Panel input changed: {key}')
        inputs[key] = pl.read_parquet(path)
    events = tomllib.loads((panel/'corporate_actions.toml').read_text(encoding='utf-8'))['splits']
    receipt = {'status':'running','auto_trade':False,'account_portfolio_replayed':False,
               'panel':str(panel),'completed':[]}
    def save():
        (output/'summary.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    save()
    stock_costs = tomllib.loads(Path(spec['stock_source'],'battery.toml').read_text(encoding='utf-8'))['costs']['a_share']
    try:
        for multiplier in spec['cost_multipliers']:
            etf_costs = {k:v for k,v in spec['costs']['etf'].items() if k != 'stamp_tax'}
            etf_costs['effective_from'] = spec['pessimistic']['pre2019']['start']
            for key in ('commission_rate','commission_min','slippage_per_share'):
                etf_costs[key] *= multiplier
            settings = {'portfolio':{'initial_cash':spec['capital_cny']},
                        'costs':{'a_share':copy.deepcopy(stock_costs),'etf':etf_costs}}
            for symbol in inputs['instruments']['symbol']:
                bars = inputs['bars'].filter(pl.col('symbol') == symbol)
                dates = sorted(inputs['calendar'].filter(pl.col('is_open') &
                    pl.col('date').is_between(bars['trade_date'].min(),spec['end']))['date'].unique())
                # A first completed quote precedes initial deployment. Later
                # quarterly targets reinvest available cash; no retroactive fills.
                signals = [dates[0]]+[a for a,b in zip(dates,dates[1:])
                    if a.month != b.month and a.month in (3,6,9,12) and a != dates[0]]
                following = dict(zip(dates,dates[1:]))
                name = symbol[:6]+'_standalone'
                targets = pl.from_dicts([dict(as_of=day,execution_date=following[day],
                    symbol=symbol,weight=1.,strategy=name,strategy_version='1') for day in signals if day in following])
                states = market_states(bars,inputs['reference_prices'],events,multiplier)
                folder = output/f'{symbol}_cost_{multiplier:g}'
                folder.mkdir()
                state = {}
                nav,trades,rejects = replay(bars=bars,calendar=inputs['calendar'],
                    instruments=inputs['instruments'].filter(pl.col('symbol')==symbol),
                    targets=targets,dividends=inputs['dividends'].filter(pl.col('symbol')==symbol),
                    market_states=states,config=settings,sessions=dates,name=name,validate_once=True,
                    account_state=state)
                for label,frame in [('nav',nav),('trades',trades),('rejections',rejects),('targets',targets)]:
                    frame.write_parquet(folder/f'{label}.parquet')
                (folder/'state.json').write_text(json.dumps(state),encoding='utf-8')
                receipt['completed'].append({'symbol':symbol,'cost_multiplier':multiplier,
                    'sessions':nav.height,'trades':trades.height,'output':str(folder)})
                save()
                print(json.dumps(receipt['completed'][-1]),flush=True)
        receipt['status']='complete'
    except Exception as exc:
        receipt.update(status='failed',error=f'{type(exc).__name__}: {exc}')
        save()
        raise
    save()
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--panel',type=Path,required=True)
    parser.add_argument('--config',type=Path,default=Path('configs/research/account_portfolio_v1.toml'))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    run(panel=args.panel,config=args.config,output=args.output)


if __name__=='__main__':
    main()
