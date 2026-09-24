"""Measure complete price-envelope accounts without relabeling strict execution evidence."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

from quant.research.joint_account_report import measure


def report(output,windows):
    summary=json.loads((output/'summary.json').read_text());source=Path('artifacts/research/etf_allocation_attribution_20260922_03')
    frames={};table=[];periods=[];events=[];tickets=[];checks=[];hashes={}
    def capture(p):hashes[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest();return p
    for row in summary['results']:
        if row['status']!='COMPLETE_PRICE_STRESS_ONLY':continue
        rule,cost=row['rule'],row['cost'];folder=output/f'{rule}_{cost:g}'
        nav=pl.read_parquet(capture(folder/'nav.parquet')).to_pandas();nav['date']=pd.to_datetime(nav.date)
        nav=nav.set_index('date').loc['2024-01-02':'2026-08-31']
        nav['return']=nav.equity/np.r_[100000.,nav.equity.to_numpy()[:-1]]-1
        frames[rule,cost]=nav
        fills=pl.read_parquet(capture(folder/'trades.parquet')).to_pandas()
        plans=pl.read_parquet(capture(folder/'planned_orders.parquet')).to_pandas()
        old=pl.read_parquet(capture(source/f'{rule}_{cost:g}/nav.parquet')).to_pandas().set_index('date').loc[nav.index]
        old_return=old.equity/np.r_[100000.,old.equity.to_numpy()[:-1]]-1
        m=measure(nav['return']);ref=measure(old_return)
        table.append(dict(rule=rule,cost=cost,**m,cagr=(nav.equity.iloc[-1]/100000.)**(252/len(nav))-1,
            original_daily_return=ref['net_return'],difference_vs_original_daily_pp=100*(m['net_return']-ref['net_return']),
            original_daily_sharpe_rf2=ref['sharpe_rf2'],fees=float(fills.fee.sum()),orders=len(fills),
            mean_cash_weight=float((nav.cash/nav.equity).mean())))
        for symbol,t in fills.groupby('symbol'):
            commission_min=5*cost
            tickets.append(dict(rule=rule,cost=cost,symbol=symbol,orders=len(t),fees=float(t.fee.sum()),
                minimum_fee_orders=int(np.isclose(t.fee,commission_min,atol=1e-7).sum()),
                median_order_notional=float(t.notional.median()),minimum_order_notional=float(t.notional.min())))
        gap=(nav.equity-nav.cash-nav.market_value-nav.receivable).abs().max()
        fee_error=abs(fills.fee.sum()-nav.cumulative_fees.iloc[-1])
        merged=plans.rename(columns={'execution_date':'date','quantity':'requested_quantity'}).merge(
            fills[['date','symbol','side','quantity']],on=['date','symbol','side'],how='left')
        duplicated=bool(fills.duplicated(['date','symbol']).any())
        if gap>1e-6 or fee_error>1e-6 or duplicated or nav.cash.min()<0:raise ValueError('Account reconciliation failed')
        checks.append(dict(rule=rule,cost=cost,sessions=len(nav),equity_error=float(gap),fee_error=float(fee_error),
            nonnegative_cash=True,duplicate_fills=duplicated,
            requested_not_fully_filled=int((merged.requested_quantity!=merged.quantity.fillna(0)).sum())))
    state_path=Path('artifacts/research/market_indicators_20260922_02/market_states.parquet')
    states=pl.read_parquet(capture(state_path)).to_pandas().set_index('effective_date').market_state
    for (rule,cost),nav in frames.items():
        baseline=frames['fixed',cost]['return']
        for kind,labels in [('year',nav.index.strftime('%Y')),('month',nav.index.strftime('%Y-%m'))]:
            for period,part in nav.groupby(labels):
                m=measure(part['return']);b=measure(baseline.loc[part.index])
                periods.append(dict(rule=rule,cost=cost,kind=kind,period=period,**m,benchmark_return=b['net_return'],
                                    excess_pp=100*(m['net_return']-b['net_return'])))
        for _,segment in states.groupby(states.ne(states.shift()).cumsum()):
            if not segment.index.isin(nav.index).all():continue
            part=nav.loc[segment.index];applicable=bool((part.market_value>0).any())
            events.append(dict(rule=rule,cost=cost,state=segment.iloc[0],start=str(segment.index[0].date()),
                end=str(segment.index[-1].date()),applicable=applicable,
                **(measure(part['return']) if applicable else dict(net_return=None)),
                benchmark_return=measure(baseline.loc[segment.index])['net_return']))
    for name,rows in [('comparison',table),('annual_monthly',periods),('continuous_events',events),('order_costs',tickets)]:
        pd.DataFrame(rows).to_csv(output/f'{name}.csv',index=False)
    (output/'verification.json').write_text(json.dumps(checks,indent=2))
    # Audit every selected extreme against eligible source components, separately from strict coverage.
    env=pl.read_csv(capture(windows/'envelope_windows.csv'),try_parse_dates=True)
    components=pl.read_csv(capture(windows/'source_window_components.csv'),try_parse_dates=True)
    for r in env.filter(pl.col('envelope_eligible')).to_dicts():
        available=components.filter((pl.col('date')==r['date'])&(pl.col('symbol')==r['symbol'])&pl.col('envelope_eligible'))
        if r['high']!=available['high'].max() or r['low']!=available['low'].min():raise ValueError('Envelope selection changed')
    original=Path('artifacts/research/etf_delayed_20260924_01')
    prefix=[]
    for (rule,cost),nav in frames.items():
        previous=pl.read_parquet(capture(original/f'{rule}_{cost:g}/partial_nav.parquet')).to_pandas()
        previous['date']=pd.to_datetime(previous.date);previous=previous.set_index('date')
        common=nav.index.intersection(previous.index);difference=nav.loc[common,'equity']-previous.loc[common,'equity']
        unequal=difference[abs(difference)>1e-8]
        prefix.append(dict(rule=rule,cost=cost,first_changed_date=str(unequal.index[0].date()) if len(unequal) else None,
            largest_prefix_equity_change=float(abs(difference).max()),old_strict_status='unchanged_incomplete'))
    pd.DataFrame(prefix).to_csv(output/'strict_prefix_comparison.csv',index=False)
    summary.update(measurements=table,envelope_rule_check=True,
        conclusion='supports_frozen_forward_observation_only' if all(r['net_return']>0 and r['sharpe_rf2']>0 for r in table)
                   else 'price_stress_does_not_support_executable_candidate')
    (output/'summary.json').write_text(json.dumps(summary,indent=2))
    capture(Path(__file__));capture(output/'envelope_config.toml')
    (output/'report_manifest.json').write_text(json.dumps(hashes,indent=2))
    selected=pd.DataFrame(table)[['rule','cost','sessions','net_return','cagr','sharpe_rf0','sharpe_rf2','max_drawdown','difference_vs_original_daily_pp','fees']]
    (output/'report.md').write_text('# ETF各有效源价格包络压力情景\n\n机器生成。10万元，原动态/静态规则，从初始现金重新顺序结算645日。1/3分钟共用首5分钟保守价格边界。\n\n'
        +selected.to_markdown(index=False)+'\n\n'
        'BUY=max(有效源high)，SELL=min(有效源low)，另计三档原摩擦。开盘行单列，只有本身量额/价格有效且常规窗口有效才进入含开盘包络。'
        '同币种、未复权、时间和日内范围均核对；原0.0011容差不变。缺数据窗口仍无效，实际零净订单才不需要成交价格。\n\n'
        '原严格账户和covered未修改；本结果只作经济压力判断。含开盘外包络不是1/3分钟后能成交的竞价价格，也不是所有后续财富路径的严格下界。'
        '相对旧日线的差异同时含信号收盘股数、极值价格、费用及后续现金/整手路径影响，不是单独延迟成本。\n\n'
        '年度/月度见annual_monthly.csv，完整连续压力段见continuous_events.csv，费用与最低佣金见order_costs.csv；'
        'strict_prefix_comparison.csv展示旧199日前缀也因统一政策而变化，没有沿用旧账户前缀。\n\n结论：'+summary['conclusion']+
        '。保留RESEARCH_ONLY及既定前向观察；盘口、延迟后容量和精确来源差异仍未验证，不升级真实可交易结论。\n',encoding='utf-8')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--windows',type=Path,required=True)
    a=p.parse_args();report(a.output,a.windows)
