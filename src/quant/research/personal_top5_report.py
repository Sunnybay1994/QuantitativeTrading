"""Machine-generated paired effects, admission and full calendar-period evidence."""
import copy
import datetime as dt
import json
import math

import polars as pl

from quant.reporting.calendar_turnover import calendar_turnover, turnover_passes
from quant.reporting.multifactor_assessment import assess_model, holding_metrics
from quant.reporting.period_metrics import period_metrics, write_period_reports


def concat_years(folder, name):
    frames = [pl.read_parquet(p/name) for p in sorted(folder.iterdir()) if p.is_dir() and p.name.isdigit()]
    return pl.concat([f for f in frames if f.width], how='diagonal_relaxed')


def fees(trades, floor, cost, settings):
    rows=[]
    rate=settings['costs']['a_share']['commission_rate']*cost
    slip=settings['costs']['a_share']['slippage']*cost
    for r in trades.to_dicts():
        notional=r['notional']; day=r['date']; buy=r['side']=='BUY'
        commission=max(notional*rate,floor*cost)
        transfer=notional*(.00002 if day<dt.date(2022,4,29) else .00001)
        stamp=0. if buy else notional*(.001 if day<dt.date(2023,8,28) else .0005)
        if not math.isclose(r['fee'],commission+transfer+stamp,abs_tol=1e-6):
            raise ValueError('Trade fee does not reconcile to original historical cost model')
        # One daily fill per logical order; do not charge minimum on fragments.
        rows.append({**r,'logical_order':f"{day}|{r['symbol']}|{r['side']}",
            'commission':commission,'commission_floor_binding':notional*rate<floor*cost,
            'floor_premium':max(0.,floor*cost-notional*rate),'transfer':transfer,'stamp':stamp,
            'slippage_cost':notional/(1+slip if buy else 1-slip)*slip})
    result=pl.from_dicts(rows,infer_schema_length=None)
    if result['logical_order'].n_unique()!=result.height:
        raise ValueError('Partial logical-order fills require aggregated commission audit')
    return result


def report(output):
    from quant.research.personal_top5 import restore_dates, write_json
    settings=restore_dates(json.loads((output/'inputs/settings.json').read_text()))
    model=restore_dates(json.loads((output/'inputs/model.json').read_text()))
    windows=restore_dates(json.loads((output/'inputs/stress.json').read_text()))
    sessions=restore_dates(json.loads((output/'inputs/sessions.json').read_text()))
    benchmarks={p.stem.removeprefix('benchmark_'):pl.read_parquet(p) for p in (output/'inputs').glob('benchmark_*.parquet')}
    benchmarks['510300_total_return_reference']=benchmarks.pop('510300')
    rows=[]; data={}; outcomes=[]
    for k in (50,5):
        for floor in (5,1):
            for cost in (.5,1.,2.):
                folder=output/f'top{k}_fee{floor}_cost{cost:g}'
                frames={name:concat_years(folder,name+'.parquet') for name in ('nav','trades','rejections','orders','holdings','exposure')}
                nav,trades=frames['nav'],frames['trades']
                if nav['date'].to_list()!=sessions:
                    raise ValueError('Account history incomplete')
                for name,frame in frames.items(): frame.write_parquet(folder/f'{name}.parquet')
                metrics=holding_metrics(nav,trades,initial_cash=100000.)
                turns=calendar_turnover(nav,trades)
                metrics['annualized_one_way_turnover_252']=metrics['annualized_one_way_turnover']
                metrics['annualized_one_way_turnover']=turns['median']
                returns=nav.with_columns((pl.col('unit_nav')/pl.col('unit_nav').shift(1).fill_null(1.)-1).alias('r')).filter(pl.col('date')>=metrics['active_start'])['r']
                metrics['sharpe_rf2']=(returns.mean()-(1.02**(1/252)-1))/returns.std()*math.sqrt(252) if returns.std() else None
                fee=fees(trades,floor,cost,settings)
                fee.write_parquet(folder/'fee_attribution.parquet')
                fee_totals={col:fee[col].sum() for col in ('commission','floor_premium','transfer','stamp','slippage_cost','commission_floor_binding')}
                exposure=frames['exposure']
                risk=dict(max_actual_holdings=exposure['holdings'].max(),days_above_k=exposure['above_target_count'].sum(),
                    max_name_weight=exposure['max_name_weight'].max(),max_industry_weight=exposure['max_industry_weight'].max(),
                    max_unknown_industry_weight=exposure['unknown_industry_weight'].max(),
                    average_cash_fraction=exposure.select((pl.col('cash')/pl.col('equity')).mean()).item())
                # Pair each fixed requested delta to actual fills; corporate actions
                # remain separately represented by the authoritative account.
                actual=trades.group_by('date','symbol').agg(pl.when(pl.col('side')=='BUY').then(pl.col('quantity')).otherwise(-pl.col('quantity')).sum().alias('filled_delta'))
                audit=frames['orders'].join(actual,left_on=['execution_date','symbol'],right_on=['date','symbol'],how='left').with_columns(pl.col('filled_delta').fill_null(0)).with_columns(
                    (pl.col('requested_delta')-pl.col('filled_delta')).alias('unfilled_delta'))
                audit.write_parquet(folder/'order_fills.parquet')
                periods=period_metrics(nav,benchmarks,start=metrics['active_start'])
                description=f'10万元；冻结PIT多因子分数每月严格选前{k}名、等权并预留2%现金；信号收盘固定股数、下个交易日执行；最低佣金{floor}元，成本{cost:g}倍。历史均为开发证据，未重训。'
                write_period_reports(folder/'periods',periods,description)
                row=dict(account=folder.name,top_k=k,floor=floor,cost=cost,**metrics,fees=fee_totals,risk=risk,
                         rejected_orders=frames['rejections'].height,unfilled_orders=audit.filter(pl.col('unfilled_delta')!=0).height)
                write_json(folder/'summary.json',row)
                write_json(folder/'calendar_turnover.json',turns)
                data[k,floor,cost]=(nav,row)
                rows.append(row)
    for k in (50,5):
        for floor in (5,1):
            nav,one=data[k,floor,1.]; two=data[k,floor,2.][1]
            evaluation=copy.deepcopy(model)
            evaluation['walk_forward'].update(test_start=sessions[0],test_end=sessions[-1])
            outcome=assess_model(nav=nav,one=one,two=two,benchmarks=benchmarks,model=evaluation,windows=windows)
            reference=next(r for r in outcome['benchmarks'] if r['benchmark']==outcome['strongest_benchmark'])
            double_excess=two['cagr']-reference['cagr']
            outcome['checks']['turnover']=turnover_passes(one['annualized_one_way_turnover'],double_excess)
            outcome['conclusion']='PAPER_CANDIDATE' if all(outcome['checks'].values()) else 'REJECTED'
            outcome.update(top_k=k,floor=floor,double_cost_excess=double_excess,
                           evidence='retrospective_development_only_no_live_authorization')
            outcomes.append(outcome)
    effects=[]
    for cost in (.5,1.,2.):
        for metric in ('cagr','sharpe','sharpe_rf2','max_drawdown','annualized_one_way_turnover','mean_invested_fraction'):
            value=lambda k,f:data[k,f,cost][1][metric]
            effects.append(dict(cost=cost,metric=metric,
                concentration_at_fee5=value(5,5)-value(50,5),concentration_at_fee1=value(5,1)-value(50,1),
                fee_reduction_at_top50=value(50,1)-value(50,5),fee_reduction_at_top5=value(5,1)-value(5,5),
                interaction=(value(5,1)-value(5,5))-(value(50,1)-value(50,5))))
    write_json(output/'summary.json',dict(status='complete',accounts=rows,admission=outcomes,paired_effects=effects,
        auto_trade=False,classification='DEVELOPMENT_EVIDENCE',
        limitations=['Fee1 is a user assumption, not a verified broker tariff.',
            'Historical PIT model outputs have already been inspected; no new unseen holdout.',
            'Daily next-open replay does not validate manual execution latency or order-book capacity.',
            'STAR simulation assumes trading permission; account eligibility must be checked before any live use.',
            'Size and industry exposures use most recent available signal-date metadata; unknowns are explicit.']))
    lines=['# 10万元 Top5 / 最低佣金1元配对实验','',
        '固定冻结模型预测，完整共同历史；没有重训或扫描K。原有账户未修改。全部为历史开发证据，auto_trade=false。','',
        '|账户|持仓期年化|Sharpe rf0 / rf2|最大回撤|换手中位数|平均仓位|期间报告|',
        '|---|---:|---:|---:|---:|---:|---|']
    for r in rows:
        lines.append(f"|{r['account']}|{r['cagr']:.2%}|{r['sharpe']:.3f} / {r['sharpe_rf2']:.3f}|{r['max_drawdown']:.2%}|{r['annualized_one_way_turnover']:.3f}|{r['mean_invested_fraction']:.2%}|[年/月]({r['account']}/periods/report.md)|")
    lines+=['','## 原门槛核对','']
    for outcome in outcomes:
        failed=', '.join(key for key,passed in outcome['checks'].items() if not passed) or '无'
        lines.append(f"- Top{outcome['top_k']} / 最低佣金{outcome['floor']}元：{outcome['conclusion']}；未通过：{failed}。")
    lines+=['','## 持股数与佣金的分离影响','',
        '|成本|Top5−Top50（费5）年化差|Top5−Top50（费1）年化差|费1−费5（Top50）|费1−费5（Top5）|交互差|',
        '|---|---:|---:|---:|---:|---:|']
    for e in effects:
        if e['metric']=='cagr': lines.append('|'+str(e['cost'])+'|'+ '|'.join(f"{e[key]:.2%}" for key in ('concentration_at_fee5','concentration_at_fee1','fee_reduction_at_top50','fee_reduction_at_top5','interaction'))+'|')
    lines+=['','差值是独立账户连续复利后的配对差，包含资金路径交互，不等于静态节省手续费。',
        '逐笔固定委托/未成交/整手损失、每日真实持仓及行业/规模暴露、费率与最低佣金归因见各账户parquet；连续压力窗口见summary.json的admission/stress。',
        '科创板最低200股、1股递增使用实验专用绑定；旧快照和旧账户不改写。',
        '日线次日开盘回放未验证人工延迟、盘口容量和实盘交易权限。最低1元佣金是用户假设。','']
    (output/'report.md').write_text('\n'.join(lines),encoding='utf-8')
