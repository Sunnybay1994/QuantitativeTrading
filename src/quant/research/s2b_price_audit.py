"""Reconstruct the saved S2b daily-weight calculation before any correction."""
import argparse
import hashlib
import json
from pathlib import Path
import tomllib

import polars as pl


def reconstruct(closes,weights,*,cost,chronological=False):
    price=closes.sort('symbol','trade_date').with_columns(
        pl.col('close').shift(1).over('symbol').alias('previous_close'))
    price=price.with_columns((pl.col('close')/pl.col('previous_close')-1).alias('return'))
    positions=price.join(weights.select(pl.col('execution_date').alias('trade_date'),'symbol','weight'),
        on=['symbol','trade_date'],how='left').sort('symbol','trade_date').with_columns(
            pl.col('weight').forward_fill().over('symbol')).drop_nulls('weight')
    positions=positions.with_columns((pl.col('weight')*pl.col('return')).alias('contribution'))
    changes=[]
    previous={}
    for day in weights['execution_date'].unique().sort():
        current=dict(weights.filter(pl.col('execution_date')==day).select('symbol','weight').iter_rows())
        turnover=sum(abs(current.get(s,0.)-previous.get(s,0.)) for s in set(previous)|set(current))/2
        changes.append({'trade_date':day,'turnover':turnover})
        previous=current
    daily=positions.group_by('trade_date').agg(pl.col('contribution').sum().alias('gross'),
        pl.col('weight').sum().alias('exposure'),pl.len().alias('names')).sort('trade_date').join(
            pl.from_dicts(changes),on='trade_date',how='left')
    if chronological:
        daily=daily.sort('trade_date')
    daily=daily.with_columns((pl.col('gross')-pl.col('turnover').fill_null(0)*cost).alias('net'))
    daily=daily.with_columns((1+pl.col('net')).cum_prod().alias('unit_nav')).with_columns(
        (pl.col('unit_nav')/pl.col('unit_nav').cum_max()-1).alias('drawdown'))
    return positions,daily


def run(*,output):
    output.mkdir(parents=True,exist_ok=False)
    config=Path('configs/research/few_holdings_v1.toml')
    old=Path('artifacts/research/few_holdings_v1_20261027/s2b_etf_momentum')
    spec=tomllib.loads(config.read_text(encoding='utf-8'))
    weights=pl.read_parquet(old/'weights.parquet')
    paths=[Path('data/clean/bar_1d_tdx/source=tdx')/f'market={s[-2:]}'/f'symbol={s}/data.parquet'
        for s in spec['s2b']['pool']]
    sources=[config,old/'weights.parquet',old/'assessment.json',Path(__file__),*paths]
    (output/'manifest.json').write_text(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},indent=2))
    closes=pl.concat([pl.read_parquet(p).select('symbol','trade_date','close') for p in paths])
    closes.write_parquet(output/'closes.parquet')
    weights.write_parquet(output/'original_weights.parquet')
    positions,daily=reconstruct(closes,weights,cost=spec['s2b']['one_way_cost']*2)
    positions.write_parquet(output/'legacy_daily_positions.parquet')
    daily.write_parquet(output/'legacy_2x_nav.parquet')
    trough=daily.sort('drawdown').row(0,named=True)
    before=daily.filter(pl.col('trade_date')<=trough['trade_date'])
    peak=before.filter(pl.col('unit_nav')==before['unit_nav'].max()).tail(1).row(0,named=True)
    interval=positions.filter(pl.col('trade_date').is_between(peak['trade_date'],trough['trade_date']))
    interval.write_parquet(output/'drawdown_daily_positions.parquet')
    jumps=positions.filter(pl.col('return').abs()>.3).sort('trade_date')
    jumps.write_parquet(output/'large_price_jumps.parquet')
    original=json.loads((old/'assessment.json').read_text())
    saved=next(r for r in original['rows'] if r['cost_multiplier']==2.)
    delta=trough['drawdown']-saved['max_drawdown']
    summary={'auto_trade':False,'scope':'saved target-weight calculation, not actual-share holdings',
        'saved_2x_max_drawdown':saved['max_drawdown'],'reconstructed_2x_max_drawdown':trough['drawdown'],
        'reconstruction_delta':delta,'exact_legacy_reconstruction':abs(delta)<1e-10,
        'peak':peak,'trough':trough,'maximum_implied_exposure':daily['exposure'].max(),
        'maximum_implied_names':daily['names'].max(),'maximum_registered_names':spec['s2b']['top_k'],
        'price_jumps':jumps.select('symbol','trade_date','previous_close','close','return','weight','contribution').to_dicts(),
        'original_end':saved['report_end'],'registered_end':spec['s2b']['end'],
        'problems':['Exited names retain forward-filled weights because absent targets are not zeroed',
            'Unadjusted ETF closes mix unit scales; large jumps require independent corporate-action reconciliation',
            'The registered end date is not applied by the original runner'],
        'conclusion':'Original -77.1% is not trustworthy as an executable Top3 account drawdown; no strategy rules retuned'}
    (output/'summary.json').write_text(json.dumps(summary,indent=2,default=str),encoding='utf-8')
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(run(output=args.output),default=str))
