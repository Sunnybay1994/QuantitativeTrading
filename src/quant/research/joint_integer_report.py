"""Machine-generated order losses, execution reconciliation and paired research report."""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

from quant.backtest.daily_account import prepare_account_actions
from quant.research.joint_account_report import measure


def finish_trace(rows, states, nav, trades, rejects, bars, calendar, dividends, instruments, name):
    fills = {(r['date'], r['symbol']): r for r in trades.to_dicts()}
    refused = {}
    for r in rejects.to_dicts(): refused.setdefault((r['date'], r['symbol']), []).append(str(r['reason']))
    prices = {(r['trade_date'], r['symbol']): r['open'] for r in bars.to_dicts()}
    prepared = {d: prepare_account_actions(date=d, state=s, calendar=calendar, dividends=dividends) for d, s in states.items()}
    for r in rows:
        date = r['execution_date']; s = r['symbol']; state = prepared[date]
        open_equity = state['cash']+sum(h['quantity']*prices.get((date, symbol), h['mark_price'])
                                      for symbol, h in state['holdings'].items())
        oldq = state['holdings'].get(s, {}).get('quantity', 0)
        open_price = prices.get((date, s)); mark = r['signal_price']; eq = r['signal_equity']
        fill = fills.get((date, s), {}); actual_delta = fill.get('quantity', 0)*(1 if fill.get('side') == 'BUY' else -1)
        if name == 'joint_fixed':
            integer = math.floor(r['budget_weight']*open_equity/open_price/r['board_lot']+1e-10)*r['board_lot'] if open_price else None
            requested = integer-oldq if integer is not None else None
            r['integer_quantity'] = integer; r['net_order_quantity'] = requested
        else: requested = r['net_order_quantity']
        r.update(raw_notional=eq*r['raw_weight'], budget_notional=eq*r['budget_weight'],
            budget_gap=eq*(r['raw_weight']-r['budget_weight']),
            signal_lot_gap=eq*r['budget_weight']-r['naive_integer_quantity']*mark if mark else None,
            integer_notional_signal=r['integer_quantity']*mark if mark and r['integer_quantity'] is not None else None,
            opening_price=open_price, opening_equity=open_equity, pre_execution_quantity=oldq,
            actual_net_quantity=actual_delta, unfilled_quantity=requested-actual_delta if requested is not None else None,
            actual_notional=fill.get('notional', 0.), actual_fee=fill.get('fee', 0.), actual_slippage=fill.get('slippage_cost', 0.),
            execution_reasons=';'.join(refused.get((date, s), [])),
            requested_notional_open=abs(requested)*open_price if requested is not None and open_price else None)
        if requested is not None and requested != actual_delta and not r['execution_reasons']:
            r['execution_reasons'] = 'unfilled_without_rejection_check_cash_lot_or_capacity'
        if not r['price_complete']: r['loss_category'] = 'missing_signal_price'
        elif name == 'integer_fixed' and not r['constraints_satisfied']: r['loss_category'] = 'constraint_infeasible_hold'
        elif r['below_one_lot']: r['loss_category'] = 'original_intent_below_one_lot'
        elif not requested and abs(r['budget_notional']-r['current_quantity']*mark) > 1:
            r['loss_category'] = 'retained_or_omitted_adjustment_under_frozen_constraints'
        else: r['loss_category'] = 'net_order_or_no_change'
    return rows


def report(output, spec, cases):
    tables = {}; summaries = []; periods = []; events = []; losses = []; biases = []; orders = []
    source = Path('artifacts/research/market_indicators_20260922_02/market_states.parquet')
    states = pl.read_parquet(source).to_pandas().set_index('effective_date').market_state
    for case in cases:
        name, cost = case['rule'], case['cost']; folder = output/f'{name}_{cost:g}'
        nav = pl.read_parquet(folder/'nav.parquet').to_pandas().set_index('date')
        nav['return'] = nav.equity/np.r_[spec['capital'], nav.equity.to_numpy()[:-1]]-1
        exposure = pl.read_parquet(folder/'exposure.parquet').to_pandas().set_index('date')
        nav = nav.join(exposure[['stock_value','etf_value']]); tables[name,cost] = nav
        t = pl.read_parquet(folder/'trades.parquet').to_pandas()
        trace = pl.read_parquet(folder/'loss_trace.parquet').to_pandas()
        stock_trades = t[~t.symbol.isin(['510300.SH','511010.SH','518880.SH'])]
        row = dict(**case, **measure(nav['return']),
            cagr=(nav.equity.iloc[-1]/spec['capital'])**(252/len(nav))-1,
            mean_stock_weight=float((nav.stock_value/nav.equity).mean()),
            mean_etf_weight=float((nav.etf_value/nav.equity).mean()),
            mean_cash_weight=float((nav.cash/nav.equity).mean()),
            stock_orders=len(stock_trades), stock_fees=float(stock_trades.fee.sum()),
            stock_slippage=float(stock_trades.slippage_cost.sum()),
            stock_median_order=float(stock_trades.notional.median()),
            stock_sub1000_orders=int((stock_trades.notional<1000).sum()),
            missing_signal_price_rows=int((~trace.price_complete).sum()),
            infeasible_signals=int(trace.loc[~trace.constraints_satisfied,'as_of'].nunique()) if 'constraints_satisfied' in trace else 0)
        summaries.append(row)
        for asset, part in t.groupby(t.symbol.isin(['510300.SH','511010.SH','518880.SH'])):
            orders.append(dict(**case, asset='ETF' if asset else 'stocks', count=len(part),
                fees=part.fee.sum(), slippage=part.slippage_cost.sum(), notional=part.notional.sum()))
        for day, part in trace.groupby('as_of'):
            # Missing prices stay missing; sums are explicitly partial, not complete counterfactuals.
            valid = part[part.price_complete]
            losses.append(dict(**case, as_of=day, rows=len(part), complete_rows=len(valid),
                raw_notional=part.raw_notional.sum(), budget_notional=part.budget_notional.sum(),
                known_signal_lot_gap=valid.signal_lot_gap.sum(),
                missing_signal_prices=len(part)-len(valid), below_one_lot=int(part.below_one_lot.sum()),
                actual_fees=part.actual_fee.sum(), actual_notional=part.actual_notional.sum(),
                missing_opening_prices=int(part.opening_price.isna().sum()),
                unfilled_rows=int(part.unfilled_quantity.fillna(0).ne(0).sum())))
            for sector, group in part.groupby('industry', dropna=False):
                complete = bool(group.price_complete.all())
                planned = group.integer_notional_signal.sum()/group.signal_equity.iloc[0] if complete else None
                raw = group.raw_weight.sum()
                biases.append(dict(**case, as_of=day, dimension='industry', bucket=sector,
                    complete=complete, raw_weight=raw, integer_weight=planned,
                    deviation=planned-raw if planned is not None else None))
            valid = valid[valid.integer_notional_signal.notna()]
            for column in ['signal_price','size','score']:
                raw_denom = valid.raw_weight.sum(); plan_denom = valid.integer_notional_signal.sum()
                covered = valid[column].notna().all() and len(valid) == len(part)
                raw_mean = float((valid[column]*valid.raw_weight).sum()/raw_denom) if covered and raw_denom else None
                plan_mean = float((valid[column]*valid.integer_notional_signal).sum()/plan_denom) if covered and plan_denom else None
                biases.append(dict(**case, as_of=day, dimension='weighted_mean', bucket=column, complete=bool(covered),
                    raw_weight=raw_mean, integer_weight=plan_mean,
                    deviation=plan_mean-raw_mean if plan_mean is not None and raw_mean is not None else None))
    for case in cases:
        name,cost=case['rule'],case['cost'];nav=tables[name,cost];baseline=tables['joint_fixed',cost]
        for kind, labels in [('year',nav.index.strftime('%Y')),('month',nav.index.strftime('%Y-%m'))]:
            for period, part in nav.groupby(labels):
                m=measure(part['return']);b=measure(baseline.loc[part.index,'return'])
                periods.append(dict(**case,kind=kind,period=period,**m,benchmark_return=b['net_return'],
                    excess_pp=100*(m['net_return']-b['net_return']),mean_stock_weight=(part.stock_value/part.equity).mean()))
        for _, event in states.groupby(states.ne(states.shift()).cumsum()):
            if not event.index.isin(nav.index).all(): continue
            part=nav.loc[event.index];applicable=bool((part.market_value>0).any())
            events.append(dict(**case,state=event.iloc[0],start=str(event.index[0].date()),end=str(event.index[-1].date()),
                applicable=applicable,**(measure(part['return']) if applicable else dict(net_return=None)),
                baseline_return=measure(baseline.loc[event.index,'return'])['net_return']))
    for filename, rows in [('annual_monthly',periods),('continuous_events',events),('signal_losses',losses),
                           ('price_industry_bias',biases),('asset_costs',orders),('comparison',summaries)]:
        pd.DataFrame(rows).to_csv(output/f'{filename}.csv',index=False)
    comparisons=[]
    for cost in spec['cost_multipliers']:
        new=next(r for r in summaries if r['rule']=='integer_fixed' and r['cost']==cost)
        old=next(r for r in summaries if r['rule']=='joint_fixed' and r['cost']==cost)
        comparisons.append(dict(cost=cost,return_difference_pp=100*(new['net_return']-old['net_return']),
            sharpe_rf2_difference=new['sharpe_rf2']-old['sharpe_rf2'],stock_fee_difference=new['stock_fees']-old['stock_fees'],
            stock_exposure_difference=new['mean_stock_weight']-old['mean_stock_weight']))
    improved=all(r['return_difference_pp']>0 and r['sharpe_rf2_difference']>0 for r in comparisons)
    decision='RESEARCH_ONLY_no_independent_validation' if improved else 'STOP_THIS_CONSTRUCTION_BRANCH_no_robust_paired_improvement'
    (output/'summary.json').write_text(json.dumps(dict(results=summaries,comparisons=comparisons,decision=decision,auto_trade=False),indent=2))
    (output/'report_manifest.json').write_text(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [source,Path(__file__)]},indent=2))
    table=pd.DataFrame(summaries)[['rule','cost','net_return','cagr','sharpe_rf0','sharpe_rf2','max_drawdown','mean_stock_weight','stock_orders','stock_fees','infeasible_signals']]
    (output/'report.md').write_text('# 10万元整手与费用感知构建实验\n\n机器生成。原预测、原50候选、名义股票/固定ETF各50%；只冻结一条规则。\n\n'
        +table.to_markdown(index=False)+'\n\n'+pd.DataFrame(comparisons).to_markdown(index=False)+'\n\n结论：'+decision+'。\n\n'
        'rf2使用年有效2%换算逐日扣除。费用是实际现金支出，差额不是删费反事实收益。\n\n'
        'loss_trace.parquet逐笔保存原始意向、预算后目标、整手目标、净订单和真实模拟成交；signal_losses.csv逐信号列缺口。'
        '缺失信号价格保持空值，已知部分的整手损耗不冒充完整分解。price_industry_bias.csv显示价格、规模、预测与行业偏移。\n\n'
        '费用上限固定以1x模型推导，三档成本不重选门槛。退出豁免小额门槛；风险/停牌/缺数据导致不可行时持有实际份额，记录失败而不放松约束。'
        '股票在信号收盘固定净份额，次日开盘重新核验交易规则与可用现金；ETF沿用原权重执行。\n\n'
        '年度/月度见annual_monthly.csv，连续压力事件见continuous_events.csv，费用与暴露见asset_costs.csv、comparison.csv。'
        '收益基准为同资金静态联合净账户；这不是正式收益指数准入。较高股票仓位的额外风险不能称alpha。\n\n'
        '2024-01-02至2026-08-31为已观察645日开发历史，不是OOS、不证明人工延迟后可交易。未改旧观察、比例或状态择时。\n',encoding='utf-8')
