"""Continuous fixed-exposure versus B16 rule replay through the existing account engine."""
import argparse
import copy
import datetime as dt
import hashlib
import json
import tomllib
from pathlib import Path

import polars as pl

from quant.data.etf_paper_inputs import etf_session_states
from quant.research.classic_monthly_baseline import replay
from quant.research.monthly_etf import read_inputs, monthly_targets
from quant.research.run_s1_walk_forward import metrics
from quant.strategies.inverse_volatility import InverseVolatilityStrategy


def frozen_targets(dynamic):
    first=dynamic['execution_date'].min()
    weights=dynamic.filter(pl.col('execution_date')==first).select('symbol','weight')
    return dynamic.drop('weight').join(weights,on='symbol',how='left'),weights


def run(config,output):
    settings=tomllib.loads(config.read_text(encoding='utf-8'))
    if settings['auto_trade'] is not False or settings['capital']!=100000:
        raise ValueError('Require manual-only 100k research')
    output.mkdir(parents=True,exist_ok=False)
    (output/'config.toml').write_bytes(config.read_bytes())
    basepath=Path(settings['source_config'])
    base=tomllib.loads(basepath.read_text(encoding='utf-8'))
    base['portfolio']['initial_cash']=settings['capital']
    symbols=tuple(sorted(base['universe']['symbols']))
    bars,prices,calendar,instruments,dividends=read_inputs(Path('data'),symbols,base['data'])
    frames=dict(bars=bars,prices=prices,calendar=calendar,instruments=instruments,dividends=dividends)
    hashes={}
    for name,frame in frames.items():
        path=output/(name+'.parquet')
        frame.write_parquet(path)
        hashes[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    (output/'freeze.json').write_text(json.dumps(dict(created_at=dt.datetime.now().astimezone().isoformat(),inputs=hashes,source_config_sha256=hashlib.sha256(basepath.read_bytes()).hexdigest(),code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),indent=2),encoding='utf-8')
    sessions=calendar.filter((pl.col('market')=='SH')&pl.col('is_open')&pl.col('date').is_between(settings['start'],settings['end']))['date'].sort().to_list()
    for symbol in symbols:
        for frame in (bars,prices):
            actual=frame.filter((pl.col('symbol')==symbol)&pl.col('trade_date').is_in(sessions))
            if actual.height!=len(sessions) or actual['trade_date'].n_unique()!=len(sessions):
                raise ValueError('Incomplete or duplicated continuous input')
    strategy=InverseVolatilityStrategy(symbols,60,name='b16_dynamic')
    dynamic=monthly_targets(prices,calendar,start=settings['start'],end=settings['end'],candidates=symbols,name='b16_dynamic',strategy=strategy)
    fixed,weights=frozen_targets(dynamic)
    if dynamic['as_of'].min()>=settings['start']:
        raise ValueError('Initial weights must predate replay')
    weights.write_csv(output/'frozen_weights.csv')
    results=[]
    for cost in settings['cost_multipliers']:
        scenario=copy.deepcopy(base)
        for key in ('commission_rate','commission_min','slippage','slippage_per_share'):
            scenario['costs']['etf'][key]*=cost
        states=etf_session_states(bars,dividends,slippage=scenario['costs']['etf']['slippage'],slippage_per_share=scenario['costs']['etf']['slippage_per_share'])
        for name,targets in [('dynamic',dynamic),('fixed',fixed)]:
            targets=targets.with_columns(pl.lit(name).alias('strategy'))
            nav,trades,rejects=replay(bars=bars,calendar=calendar,instruments=instruments,targets=targets,dividends=dividends,market_states=states,config=scenario,sessions=sessions,name=name,validate_once=True)
            folder=output/f'{name}_{cost:g}'
            folder.mkdir()
            for label,frame in [('nav',nav),('trades',trades),('rejections',rejects),('targets',targets)]:
                frame.write_parquet(folder/(label+'.parquet'))
            results.append(dict(rule=name,cost=cost,**metrics(nav,trades,initial_cash=settings['capital'])))
            print(f'completed {name} {cost:g}x',flush=True)
    result=dict(classification='RESEARCH_ONLY',sessions=len(sessions),start=str(settings['start']),end=str(settings['end']),weights=weights.to_dicts(),results=results,limitations=['Already observed history, not independent OOS.', 'Fixed weights use only pre-start information; no full-sample fitting.', 'One continuous account per scenario, no stitching short folds.', 'No new combined Q10 account or changed B16/B20 admission.'])
    (output/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    table=pl.DataFrame(results).select('rule','cost','total_return','sharpe','max_drawdown','annualized_one_way_turnover').to_pandas().to_markdown(index=False)
    (output/'report.md').write_text('# ETF固定暴露与动态规则归因\n\n'+table+'\n\n'+json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',type=Path,default=Path('configs/research/etf_allocation_attribution_v1.toml'))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    run(args.config,args.output)


if __name__=='__main__':
    main()
