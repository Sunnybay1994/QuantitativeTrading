"""Saved-battery failure decomposition and explanatory allocation baselines."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl


def period_metrics(returns):
    nav=np.r_[1.,np.cumprod(1+returns.to_numpy())]
    std=returns.std(ddof=1)
    return dict(return_value=float(nav[-1]-1),max_drawdown=float(np.min(nav/np.maximum.accumulate(nav)-1)),
                sharpe_rf0=float(returns.mean()/std*np.sqrt(252)) if std>0 else None,
                sharpe_rf2=float((returns.mean()-.02/252)/std*np.sqrt(252)) if std>0 else None,
                sessions=len(returns))


def run(output,allocation):
    output.mkdir(parents=True,exist_ok=False)
    sources={}
    def record(path):
        sources[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
        return path
    root=Path('artifacts/factors/nightly_batches/6b35e47b1f0dcf04/evaluation')
    names=['pressure_reversal_high_amount_v1','ngp_804a131ba8cb5a88','ngp_bbcc07585bc35fbe']
    frame=pl.read_parquet(record(root/'scorecard/factor_scorecard.parquet')).filter(pl.col('factor').is_in(names))
    rows=[]
    for r in frame.to_dicts():
        row={k:r[k] for k in ['factor','variant','months','mean_ic','icir','newey_west_t','long_short_sharpe','factor_admitted','decay','group_statistics']}
        row['monthly_label']='next_open_to_next_monthly_rebalance_open'
        row['gross_account_return']=None
        row['factor_specific_style_pnl']=None
        row['missing_evidence']='No zero-cost account or dedicated realized style-contribution series consumed; group spreads are uncosted label diagnostics, not tradable short-account profits.'
        row['costs']={str(cost):{key:r[f'cost_{prefix}_{key}'] for key in ['cagr','sharpe','max_drawdown','annualized_one_way_turnover','all_market_equal_weight_cagr_excess']} for cost,prefix in [(0.5,'0p5'),(1,'1'),(2,'2')]}
        row['cagr_1_to_2_difference_pp']=100*(r['cost_2_cagr']-r['cost_1_cagr'])
        row['cost_difference_caveat']='Includes changed holdings/cash/executions; not pure fee drag or an inferred gross return.'
        rows.append(row)
    pair=pl.read_parquet(record(root/'redundancy/pairwise_correlations.parquet')).filter(pl.col('left').is_in(names[1:])&pl.col('right').is_in(names[1:]))
    pair.write_csv(output/'quality_pair_correlation.csv')
    daily=Path('artifacts/daily/sue_v2/2026-09-21_213004_783773')
    capture=json.loads(record(daily/'candidate_forward/summary.json').read_text(encoding='utf-8'))
    scoring=json.loads(record(daily/'candidate_scoring/summary.json').read_text(encoding='utf-8'))
    # These financial mechanisms have already completed the battery; consume
    # their saved forward capture instead of enqueueing the same expressions.
    values=pl.read_parquet(record(daily/'candidate_forward/values.parquet'))
    values.select('symbol','trade_date',*names[1:]).write_parquet(output/'existing_forward_values.parquet')
    coverage=[]
    for name in names[1:]:
        finite=values.filter(pl.col(name).is_finite())
        coverage.append(dict(factor=name,total_rows=values.height,finite_rows=finite.height,
                             unique_scores=finite[name].n_unique(),
                             binary_tie_warning=finite[name].n_unique()<=2))
    period_rows=[]
    for cost in [.5,1.,2.]:
        return_series={}
        for name in ['dynamic','fixed']:
            nav=pl.read_parquet(record(allocation/f'{name}_{cost:g}/nav.parquet')).to_pandas().sort_values('date').set_index('date')['equity']
            ret=nav.pct_change(fill_method=None)
            ret.iloc[0]=nav.iloc[0]/100000-1
            return_series[name]=ret
        for name,ret in return_series.items():
            for frequency in ['Y','M']:
                for period,part in ret.groupby(ret.index.to_period(frequency)):
                    baseline=return_series['fixed'].reindex(part.index)
                    values_metrics=period_metrics(part)
                    period_rows.append(dict(rule=name,cost=cost,frequency=frequency,period=str(period),
                        start=str(part.index.min().date()),end=str(part.index.max().date()),
                        excess_vs_fixed_pp=100*(values_metrics['return_value']-period_metrics(baseline)['return_value']),**values_metrics))
    pd.DataFrame(period_rows).to_csv(output/'annual_monthly.csv',index=False)
    weights=pd.read_csv(record(allocation/'frozen_weights.csv')).set_index('symbol')['weight']
    q10=pd.read_csv(record(Path('artifacts/research/strategy_family_regimes_20260922_01/daily_returns_1x.csv')),parse_dates=['date']).set_index('date')['Q10 budget']
    prices=pl.read_parquet(record(allocation/'prices.parquet')).to_pandas()
    bond=prices[prices.symbol=='511010.SH'].set_index('trade_date')['adjusted_close'].sort_index().pct_change(fill_method=None)
    nav=pl.read_parquet(record(allocation/'dynamic_1/nav.parquet')).to_pandas().sort_values('date').set_index('date')['equity']
    dynamic=nav.pct_change(fill_method=None)
    dynamic.iloc[0]=nav.iloc[0]/100000-1
    common=pd.concat([dynamic.rename('dynamic'),q10.rename('q10'),bond.rename('bond')],axis=1,join='inner').dropna()
    w=float(weights['510300.SH'])
    common['q10_cash_proxy']=w*common.q10
    common['q10_bond_proxy']=w*common.q10+(1-w)*common.bond
    common.to_csv(output/'common_explanatory_returns.csv')
    comparisons={key:period_metrics(common[key]) for key in ['dynamic','q10','q10_cash_proxy','q10_bond_proxy']}
    result=dict(battery=rows,quality_pair_correlation=pair.to_dicts(),forward_capture_status=capture.get('status'),forward_scored_months=scoring['scored_months'],
                forward_mechanisms=names[1:],forward_coverage=coverage,common_baselines=comparisons,proxy_q10_weight=w,
                limits=['Explanatory scaled returns only, not merged-order backtests; no new combined portfolio.', 'Q10 component has saved 1x costs, proxy rebalance/lot costs unmodeled.', 'Proxy weights determined from pre-start ETF exposure, not fitted to returns.', 'Future monthly labels remain immature; no new factor admission or strategy promotion.'])
    (output/'source_manifest.json').write_text(json.dumps(sources,indent=2),encoding='utf-8')
    (output/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    annual=pd.DataFrame(period_rows)
    annual=annual[(annual.frequency=='Y')&(annual.cost==1)]
    (output/'report.md').write_text('# 机制失效来源与简单配置对照\n\n'+pd.DataFrame(comparisons).T.to_markdown()+'\n\n## 年度表现（1×，边界年按实际区间）\n\n'+annual.to_markdown(index=False)+'\n\n[全部年/月及三档成本](annual_monthly.csv) · [结构化诊断](report.json)\n\n'+json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps(dict(forward_capture_status=result['forward_capture_status'],scored_months=result['forward_scored_months'],common_baselines=comparisons),ensure_ascii=False))
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--allocation',type=Path,required=True)
    args=parser.parse_args()
    run(args.output,args.allocation)


if __name__=='__main__':
    main()
