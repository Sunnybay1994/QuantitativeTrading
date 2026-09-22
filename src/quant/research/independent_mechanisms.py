"""Consume existing pressure battery and ETF executions; no search or admission changes."""
import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd
import polars as pl


def turnover_breakdown(notional, initial_deployment, capital, sessions):
    if capital<=0 or sessions<=0 or not 0<=initial_deployment<=notional:
        raise ValueError('Invalid turnover inputs')
    return (notional/(2*capital)*252/sessions,
            (notional-initial_deployment)/(2*capital)*252/sessions)


def run(output):
    output.mkdir(parents=True,exist_ok=False)
    sources={}
    def record(path):
        sources[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
        return path
    batch=Path('artifacts/research/continuous/batch_000012/2026-09-20')
    n3=json.loads(record(batch/'N3/result.json').read_text())
    score=pl.read_parquet(record(Path(n3['scorecard'])))
    selected=score.filter(pl.col('family').str.starts_with('pressure_reversal'))
    selected.write_parquet(output/'pressure_scorecard.parquet')
    columns=['factor','variant','months','mean_ic','icir','newey_west_t','statistical_pass','cost_excess_pass','redundancy_pass','cost_1_cagr','cost_1_all_market_equal_weight_cagr_excess','cost_2_all_market_equal_weight_cagr_excess','higher_max_absolute_rank_correlation']
    selected.select(columns).write_csv(output/'pressure_summary.csv')
    q10=pd.read_csv(record(Path('artifacts/research/strategy_family_regimes_20260922_01/daily_returns_1x.csv')),parse_dates=['date']).set_index('date')['Q10 budget']
    summaries=[]
    diagnostics=[]
    targets=[]
    for manifest in sorted(Path('artifacts/research/runs').glob('*/run.json')):
        run=json.loads(manifest.read_text(encoding='utf-8'))
        name=run.get('strategy_name','')
        if name not in ('b16_cross_asset_inverse_volatility60','b13_cross_asset_dual_momentum','b48_weekly_etf_reversal'):
            continue
        record(manifest)
        root=manifest.parent
        report=json.loads(record(root/'report.json').read_text())
        nav=pl.read_parquet(record(root/'nav.parquet')).to_pandas()
        trades=pl.read_parquet(record(root/'trades.parquet')).to_pandas()
        target=pl.read_parquet(record(root/'targets.parquet')).to_pandas()
        for row in report['results']:
            if row['comparison']=='strategy':
                summaries.append(dict(strategy=name,run=str(root),original_conclusion=report['conclusion'],**row))
        for fold in sorted(nav['fold'].unique()):
            n=nav[(nav['fold']==fold)&(nav['period']=='test')&(nav['comparison']=='strategy')&(nav['cost_multiplier']==1)].sort_values('date')
            t=trades[(trades['fold']==fold)&(trades['period']=='test')&(trades['comparison']=='strategy')&(trades['cost_multiplier']==1)]
            if n.empty:
                continue
            # Include initial deployment P&L from the frozen initial cash.
            import tomllib
            cfg=tomllib.loads(record(root/'config.toml').read_text())
            initial=cfg['portfolio']['initial_cash']
            returns=n.set_index('date')['equity'].pct_change(fill_method=None)
            returns.iloc[0]=n.iloc[0]['equity']/initial-1
            pair=pd.concat([returns.rename('etf'),q10.rename('q10')],axis=1,join='inner').dropna()
            pair.to_csv(output/f'{name}_fold{fold}_common_returns.csv')
            first_date=t['date'].min()
            first_notional=t.loc[t['date']==first_date,'notional'].sum()
            total=t['notional'].sum()
            full,ongoing=turnover_breakdown(total,first_notional,initial,len(n))
            saved=next(r for r in report['results'] if r['fold']==fold and r['comparison']=='strategy' and r['cost_multiplier']==1)
            if abs(full-saved['annualized_one_way_turnover'])>1e-8:
                raise ValueError('Saved turnover reconciliation failed')
            if not pair.index.is_unique:
                raise ValueError('Duplicate common return dates')
            row=dict(strategy=name,fold=int(fold),sessions=len(n),common_sessions=len(pair),
                     common_correlation=float(pair['etf'].corr(pair['q10'])),
                     q10_down_correlation=float(pair.loc[pair.q10<0,'etf'].corr(pair.loc[pair.q10<0,'q10'])),
                     gross_notional=float(total),initial_deployment_notional=float(first_notional),
                     original_turnover_recomputed=full,ongoing_turnover_diagnostic=ongoing,
                     original_failed_checks=[k for k,v in report['admission'].items() if not v])
            diagnostics.append(row)
            w=target[(target['fold']==fold)&(target['period']=='test')&(target['comparison']=='strategy')]
            for symbol,group in w.groupby('symbol'):
                targets.append(dict(strategy=name,fold=int(fold),symbol=symbol,mean_target_weight=float(group.weight.mean())))
    pd.DataFrame(summaries).to_csv(output/'etf_three_cost_results.csv',index=False)
    pd.DataFrame(diagnostics).to_csv(output/'etf_execution_diagnostics.csv',index=False)
    pd.DataFrame(targets).to_csv(output/'etf_target_exposure.csv',index=False)
    forward_root=Path('artifacts/forward/b20/cost_1/strategy')
    dated=sorted(p for p in forward_root.glob('????-??-??') if p.is_dir())
    latest=dated[-1]
    forward_nav=pd.read_csv(record(latest/'nav.csv')).sort_values('date').iloc[-1]
    positions=pd.read_csv(record(latest/'positions.csv'))
    state=json.loads(record(latest/'state.json').read_text())
    positions['market_value']=positions.quantity*positions.mark_price
    receivable=sum(r['amount'] for r in state['receivables'])
    reconstructed=state['cash']+positions.market_value.sum()+receivable
    error=float(reconstructed-forward_nav.equity)
    if abs(error)>.01 or str(forward_nav['date'])!=latest.name:
        raise ValueError('Forward account reconciliation failed')
    positions['equity_fraction']=positions.market_value/forward_nav.equity
    positions.to_csv(output/'b20_actual_positions.csv',index=False)
    forward=dict(date=latest.name,equity=float(forward_nav.equity),cash=state['cash'],receivable=receivable,reconciliation_error=error,
                 original_capital=1000000,assessment_date='2026-11-30',assessment='pending_original_endpoint',
                 comment='Existing frozen account only; no new capacity replay or early admission.')
    result=dict(pressure_batch=str(batch),pressure_rows=selected.height,etf_folds=diagnostics,b20_forward=forward,
                limits=['Historical diagnostic only; no new OOS or admission.', 'Ongoing turnover excluding initial deployment is explanatory only; original threshold includes deployment.', 'Correlation uses intersecting observed dates; folds and missing dates never spliced into portfolio NAV.', 'Target weights are not realized holdings. No merged account has been tested.'])
    (output/'source_manifest.json').write_text(json.dumps(sources,indent=2),encoding='utf-8')
    (output/'diagnosis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# 独立机制与执行诊断','', '基于已有冻结产物；不改变准入或已有前向观察。','', '## 压力反转及控制','', selected.select(columns).to_pandas().to_markdown(index=False),'','## ETF逐折执行与共同日期相关性','',pd.DataFrame(diagnostics).to_markdown(index=False),'','## 目标暴露（非实际持仓）','',pd.DataFrame(targets).to_markdown(index=False),'','## B20 已有模拟账户对账','',json.dumps(forward,ensure_ascii=False),positions.to_markdown(index=False),'','## 边界','',*result['limits']]
    (output/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    run(args.output)


if __name__=='__main__':
    main()
