"""R3 existing-account size contrast, limit-day fills and unfilled-cash bounds."""
import argparse
import datetime as dt
import json
from pathlib import Path
import tomllib

import numpy as np
import polars as pl
from scipy.stats import norm

from quant.data.equal_weight_index import load_return_benchmarks
from quant.data.factor_battery_inputs import read_battery_execution,read_daily_replay_limits
from quant.reporting.cycle_stress import path_statistics

START,END=dt.date(2019,1,2),dt.date(2026,8,31)


def history(folder,kind):
    paths=sorted(folder.glob(f'*/{kind}.parquet'))
    frames=[pl.read_parquet(p) for p in paths]
    if kind=='nav':
        frames=[f.select('date','equity','cash','market_value','unit_nav') for f in frames]
    return pl.concat(frames).sort('date')


def excess_interval(nav,baseline,*,trials,lags=3):
    """Monthly HAC interval with a disclosed Bonferroni trial-count sensitivity."""
    returns=nav.select('date','unit_nav').with_columns(pl.col('unit_nav').log().diff().alias('log_return'))
    reference=baseline.with_columns(pl.col('unit_nav').log().diff().alias('benchmark_log_return')).select('date','benchmark_log_return')
    monthly=returns.join(reference,on='date').filter(pl.col('date').is_between(START,END)).with_columns(
        pl.col('date').dt.truncate('1mo').alias('month')).group_by('month').agg(
            (pl.col('log_return')-pl.col('benchmark_log_return')).sum().alias('excess_log')).sort('month')
    values=monthly['excess_log'].to_numpy()
    centered=values-values.mean()
    variance=float(centered@centered/len(values))
    for lag in range(1,lags+1):
        variance+=2*(1-lag/(lags+1))*float(centered[lag:]@centered[:-lag]/len(values))
    standard_error=np.sqrt(max(0,variance)/len(values))
    critical=norm.ppf(1-.025/trials)
    benchmark_cagr=path_statistics(baseline,start=START,end=END)['cagr']
    interval=[(1+benchmark_cagr)*np.expm1(12*(values.mean()+sign*critical*standard_error)) for sign in (-1,1)]
    return {'months':len(values),'hac_lags':lags,'declared_trials':trials,'familywise_alpha':.05,
        'annual_log_excess_mean':float(12*values.mean()),'annual_log_excess_mean_se':float(12*standard_error),
        'conditional_annual_excess_interval_pp':[float(v*100) for v in interval],
        'interpretation':'Conditional stationary monthly log-excess estimate with fixed historical benchmark CAGR; Bonferroni sensitivity, not an unseen-OOS prediction interval'}


def run(*,output):
    output.mkdir(parents=True,exist_ok=False)
    source=Path('artifacts/models/q10_sue_v2_turnover_budget_05_20260912_01')
    base=tomllib.loads((source/'battery.toml').read_text(encoding='utf-8'))
    model=tomllib.loads((source/'model.toml').read_text(encoding='utf-8'))
    benchmarks=load_return_benchmarks(config=Path('configs/data/return_benchmarks_q1b_20260912.toml'),
        data_root=Path('data'),start=model['walk_forward']['test_start'],end=END)
    strongest=max(benchmarks,key=lambda k:path_statistics(benchmarks[k],start=START,end=END)['cagr'])
    benchmark=benchmarks[strongest]
    pairs=[]
    for cost in (.5,1.,2.):
        for mode in ('off','on'):
            path=Path(f'artifacts/portfolio/q10_sizing_v1_20261010/b0.5_k50_size_{mode}/budgeted/cost_{cost:g}')
            nav=history(path,'nav')
            if not nav['date'].equals(benchmark['date']):
                raise ValueError('Size contrast grids differ')
            metrics=path_statistics(nav,start=START,end=END)
            pairs.append({'size_neutral':mode,'cost_multiplier':cost,'source':str(path),**metrics,
                'net_cagr_excess_strongest':metrics['cagr']-path_statistics(benchmark,start=START,end=END)['cagr']})
    nav=history(source/'budgeted/cost_1','nav')
    trades=history(source/'budgeted/cost_1','trades').filter(pl.col('date').is_between(START,END))
    rejects=history(source/'budgeted/cost_1','rejections').filter(pl.col('date').is_between(START,END))
    checks=[]
    for year in range(START.year,END.year+1):
        part=trades.filter(pl.col('date').dt.year()==year)
        symbols=part['symbol'].unique().sort().to_list()
        inputs=read_battery_execution(data_root=Path('data'),refresh_config=Path(base['data']['refresh_config']),
            snapshot='factor_battery_20260911_v2',start=max(START,dt.date(year,1,1)),end=min(END,dt.date(year,12,31)),symbols=symbols)
        limits=read_daily_replay_limits(data_root=Path('data'),snapshot='limits_20260911',
            start=max(START,dt.date(year,1,1)),end=min(END,dt.date(year,12,31)),symbols=symbols)
        bands=pl.concat([inputs['limits'].select('symbol','trade_date','up_limit','down_limit'),
            limits.select('symbol','trade_date','up_limit','down_limit')]).unique(['symbol','trade_date'],keep='first',maintain_order=True)
        joined=part.join(inputs['bars'].select('symbol',pl.col('trade_date').alias('date'),'open','close'),
            on=['symbol','date'],how='left').join(bands.rename({'trade_date':'date'}),on=['symbol','date'],how='left')
        joined=joined.with_columns((pl.col('price')+pl.when(pl.col('side')=='BUY').then(-1).otherwise(1)
            *pl.col('slippage_cost')/pl.col('quantity')).alias('matched_quote'))
        joined=joined.with_columns((pl.col('up_limit').is_not_null() & pl.col('down_limit').is_not_null()).alias('bands_known'),
            ((pl.col('close')-pl.col('up_limit')).abs()<.005).alias('close_up_limit'),
            ((pl.col('close')-pl.col('down_limit')).abs()<.005).alias('close_down_limit'),
            ((pl.col('matched_quote')-pl.col('up_limit')).abs()<.005).alias('quote_up_limit'),
            ((pl.col('matched_quote')-pl.col('down_limit')).abs()<.005).alias('quote_down_limit'))
        checks.append(joined)
    fills=pl.concat(checks)
    fills.write_parquet(output/'limit_day_fills.parquet')
    buys=rejects.filter(pl.col('side')=='BUY').with_columns(
        (pl.col('reference_price')*pl.col('rejected_quantity')).alias('unfilled_notional'))
    # Several restrictions may reject the same intent: use the maximum per name,
    # never sum the same requested shares again across reasons.
    failed=buys.group_by('date','symbol').agg(pl.col('unfilled_notional').max()).group_by('date').agg(pl.col('unfilled_notional').sum())
    cash=nav.filter(pl.col('date').is_between(START,END)).join(failed,on='date',how='left').with_columns(
        pl.col('unfilled_notional').fill_null(0)).with_columns(
        (pl.col('cash')/pl.col('equity')).alias('cash_fraction'),
        (pl.min_horizontal('cash','unfilled_notional')/pl.col('equity')).alias('unfilled_cash_fraction_upper_bound'))
    cash.write_parquet(output/'unfilled_cash_bound.parquet')
    rows=pl.read_parquet('artifacts/registry/experiments.parquet').filter(pl.col('level')=='strategy')
    narrow=rows.filter(pl.col('experiment_id').str.contains(r'(?i)^q(?:[1-9]|10)(?:[^0-9]|$)')).height
    result={'auto_trade':False,'strongest_benchmark':strongest,'size_contrast':pairs,
        'size_interpretation':'Existing matched 1m b0.5 Top50 accounts; a size-constrained construction contrast, not proof of causal size-independent alpha',
        'fills':fills.height,'official_band_coverage':fills['bands_known'].mean(),
        'close_limit_day_fill_fraction':fills.select((pl.col('close_up_limit')|pl.col('close_down_limit')).mean()).item(),
        'execution_quote_at_band_fraction':fills.select((pl.col('quote_up_limit')|pl.col('quote_down_limit')).mean()).item(),
        'adverse_execution_band_fraction':fills.select(((pl.col('quote_up_limit')&(pl.col('side')=='BUY'))
            |(pl.col('quote_down_limit')&(pl.col('side')=='SELL'))).mean()).item(),
        'missing_bar_rows':fills['open'].null_count(),
        'mean_cash_fraction':cash['cash_fraction'].mean(),
        'mean_unfilled_cash_fraction_upper_bound':cash['unfilled_cash_fraction_upper_bound'].mean(),
        'unfilled_cash_interpretation':'0 to min(actual end cash, maximum rejected buy notional per symbol/day); upper bound, not a causal attribution; lot residuals and buffer are separate',
        'conditional_excess_intervals':[excess_interval(nav,benchmark,trials=n) for n in (narrow,rows.height)],
        'future_planning_excess':0.,'future_interpretation':'Use zero incremental return for capital planning until independent forward evidence matures; no positive unseen-OOS interval is established'}
    (output/'summary.json').write_text(json.dumps(result,indent=2,default=str),encoding='utf-8')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=run(output=args.output)
    print(json.dumps({k:v for k,v in result.items() if k!='size_contrast'},default=str))
