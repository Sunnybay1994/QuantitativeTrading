"""Machine periods, cost and exposure attribution for the frozen joint replay."""
import json
import hashlib
from pathlib import Path
import numpy as np
import pandas as pd
import polars as pl


def measure(r):
    wealth=np.r_[1.,(1+r).cumprod().to_numpy()]
    sigma=r.std(ddof=1)
    return dict(net_return=wealth[-1]-1,sharpe_rf0=r.mean()/sigma*np.sqrt(252) if sigma>0 else None,
        sharpe_rf2=(r.mean()-(1.02**(1/252)-1))/sigma*np.sqrt(252) if sigma>0 else None,
        max_drawdown=float((wealth/np.maximum.accumulate(wealth)-1).min()),sessions=len(r))


def report(output,spec):
    result=json.loads((output/'summary.json').read_text());periods=[];events=[];contributions=[]
    frames={};asset_costs=[];etf_exposures=[]
    etf_bars=pl.read_parquet(output/'inputs/etf_bars.parquet').to_pandas()
    for row in result['results']:
        name,cost=row['rule'],row['cost'];folder=output/f'{name}_{cost:g}'
        nav=pl.read_parquet(folder/'nav.parquet').to_pandas().set_index('date').sort_index()
        nav['return']=nav.equity/np.r_[spec['capital'],nav.equity.to_numpy()[:-1]]-1
        ex=pl.read_parquet(folder/'exposure.parquet').to_pandas().set_index('date')
        nav=nav.join(ex[['stock_value','etf_value']])
        frames[name,cost]=nav
        trades=pl.read_parquet(folder/'trades.parquet').to_pandas()
        trades['asset_group']=np.where(trades.symbol.isin(['510300.SH','511010.SH','518880.SH']),'ETF','stocks')
        for asset,part in trades.groupby('asset_group'):
            asset_costs.append(dict(rule=name,cost=cost,asset_group=asset,net_orders=len(part),
                fees=part.fee.sum(),slippage=part.slippage_cost.sum(),gross_notional=part.notional.sum()))
        # These saved ETF inputs have cash dividends only, no share distributions.
        # Reconstruct quantities from actual net fills, never from desired weights.
        for symbol in ['510300.SH','511010.SH','518880.SH']:
            fills=trades[trades.symbol==symbol].copy()
            fills['signed_quantity']=fills.quantity*np.where(fills.side=='BUY',1,-1)
            quantity=fills.groupby('date').signed_quantity.sum().reindex(nav.index,fill_value=0).cumsum()
            prices=etf_bars[etf_bars.symbol==symbol].set_index('trade_date').close.reindex(nav.index)
            values=quantity*prices
            etf_exposures.append(dict(rule=name,cost=cost,symbol=symbol,mean_actual_weight=float((values/nav.equity).mean())))
    states=pl.read_parquet('artifacts/research/market_indicators_20260922_02/market_states.parquet').to_pandas().set_index('effective_date').market_state
    for row in result['results']:
        name,cost=row['rule'],row['cost'];nav=frames[name,cost]
        control=frames['joint_fixed',cost]['return']
        trades=pl.read_parquet(output/f'{name}_{cost:g}'/'trades.parquet').to_pandas()
        for kind,labels in [('year',nav.index.strftime('%Y')),('month',nav.index.strftime('%Y-%m'))]:
            for period,part in nav.groupby(labels):
                r=part['return'];metrics=measure(r);baseline=measure(control.reindex(part.index))
                fills=trades[trades.date.isin(part.index)]
                previous_equity=nav.equity.shift(1).fillna(spec['capital'])
                daily=fills.groupby('date').notional.sum().reindex(part.index,fill_value=0.)
                periods.append(dict(rule=name,cost=cost,period_kind=kind,period=period,**metrics,
                    benchmark_return=baseline['net_return'],excess_pp=100*(metrics['net_return']-baseline['net_return']),
                    benchmark='same-capital joint_fixed static ETF allocation; not volatility matched',
                    turnover_one_way=float((daily/previous_equity.reindex(part.index)/2).sum()),
                    fees=float(fills.fee.sum()),slippage=float(fills.slippage_cost.sum()),
                    mean_stock_weight=float((part.stock_value/part.equity).mean()),mean_etf_weight=float((part.etf_value/part.equity).mean())))
        for _,event in states.groupby(states.ne(states.shift()).cumsum()):
            if not event.index.isin(nav.index).all():continue
            part=nav.loc[event.index];applicable=bool((part.market_value>0).any())
            events.append(dict(rule=name,cost=cost,state=event.iloc[0],start=str(event.index[0].date()),
                end=str(event.index[-1].date()),applicable=applicable,
                **(measure(part['return']) if applicable else dict(net_return=None,max_drawdown=None,sessions=len(part)))))
        contributions.append(dict(rule=name,cost=cost,
            mean_stock_weight=float((nav.stock_value/nav.equity).mean()),mean_etf_weight=float((nav.etf_value/nav.equity).mean()),
            total_return=row['total_return'],difference_vs_half_stock_cash=row['total_return']-measure(frames['stock_cash',cost]['return'])['net_return'],
            difference_vs_joint_fixed=row['total_return']-measure(control)['net_return'],
            difference_vs_pure_q10=row['total_return']-measure(frames['q10_only',cost]['return'])['net_return']))
    pd.DataFrame(periods).to_csv(output/'annual_monthly.csv',index=False)
    pd.DataFrame(events).to_csv(output/'continuous_events.csv',index=False)
    pd.DataFrame(contributions).to_csv(output/'allocation_attribution.csv',index=False)
    pd.DataFrame(asset_costs).to_csv(output/'asset_costs.csv',index=False)
    pd.DataFrame(etf_exposures).to_csv(output/'etf_actual_exposures.csv',index=False)
    report_sources=[Path(__file__),Path('artifacts/research/market_indicators_20260922_02/market_states.parquet')]
    (output/'report_manifest.json').write_text(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in report_sources},indent=2))
    table=pd.DataFrame(result['results'])[['rule','cost','total_return','sharpe','max_drawdown','annualized_one_way_turnover','rejected_orders']]
    (output/'report.md').write_text('# 固定Q10与ETF联合账户\n\n机器生成。10万元连续账户；50%股票分配、50%ETF分配，不扫描比例。\n\n'
        +table.to_markdown(index=False)+'\n\n## 解释与限制\n\n'
        'joint_dynamic与joint_fixed仅更换ETF动态/事前固定向量，stock_cash识别加ETF相对保留现金的作用，q10_only识别降低股票分配的作用。'
        '这些差异包含整手、费用及顺序资金约束的交互，不是可加总的因果收益贡献。\n\n'
        'allocation_attribution.csv为实际股票/ETF仓位和三种对照差异；asset_costs.csv分开股票/ETF净订单费用；etf_actual_exposures.csv由实际成交份额和价格重建债券/黄金/股指ETF平均仓位，不能把低波动债券暴露当成股票alpha。\n\n'
        '静态对照使用相同事前资本分配，不声称实现波动相同；未使用全区间波动率匹配。年度/月度相对超额基准为joint_fixed实际净账户。'
        '此处是组合机制对照，不替代正式准入所需收益指数基准。\n\n'
        '原始意向在每档账户上重算股票预算；ETF不参与股票退出预算；合并成每标的一条目标，资金不足由原引擎整手缩量、保留现金。'
        '目标不能成交、费用、买入优先级均是已有日账户模型，尚未验证人工延迟。\n\n'
        '共同区间截至2026-08-31（Q10冻结数据截止），不是ETF单独651日全段；已经观察的短历史，仅开发检验，不是OOS或准入。'
        '未运行状态择时，没有改旧账户。\n',encoding='utf-8')
