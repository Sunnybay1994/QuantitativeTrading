"""R4 one-shot Top15 diagnostics using the unchanged stock admission rules."""
import argparse
import hashlib
import json
from pathlib import Path
import tomllib

import polars as pl

from quant.backtest.account_reconciliation import validate_nav
from quant.data.equal_weight_index import load_return_benchmarks
from quant.reporting.calendar_turnover import calendar_turnover, turnover_passes
from quant.reporting.cycle_stress import path_statistics
from quant.reporting.multifactor_assessment import assess_model, holding_metrics
from quant.reporting.top15_limit_v1 import fill_evidence, full_nav


def build(root, *, register=False):
    manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    for source,digest in manifest.items():
        if hashlib.sha256(Path(source).read_bytes()).hexdigest()!=digest:
            raise ValueError(f'Frozen R4 source changed before assessment: {source}')
    receipt=json.loads((root/'summary.json').read_text(encoding='utf-8'))
    spec=tomllib.loads((root/'config.toml').read_text(encoding='utf-8'))
    variant=spec['scenarios'][0]
    expected={(variant,c) for c in [.5,1.,2.]}
    if receipt['status']!='replayed' or len(receipt['completed'])!=3 or {
            (r['variant'],r['cost_multiplier']) for r in receipt['completed']}!=expected:
        raise ValueError('R4 requires its one preregistered variant at all three original costs')
    model=tomllib.loads((Path(spec['execution_source'])/'model.toml').read_text(encoding='utf-8'))
    windows=tomllib.loads(Path(model['admission']['stress_windows_config']).read_text(encoding='utf-8'))['cycle_validation']['stress_windows']
    benchmarks=load_return_benchmarks(config=Path(spec['return_benchmark_config']),data_root=Path('data'),
        start=model['walk_forward']['test_start'],end=spec['end'])
    benchmarks['510300_total_return_reference']=benchmarks.pop('510300')
    baseline=Path(spec['r4']['baseline_run'])
    rows=[];comparisons=[];navs={};selection_evidence=[];guards=[]
    for cost in [.5,1.,2.]:
        folder=root/variant/f'cost_{cost:g}'
        guards.append({'cost_multiplier':cost,**validate_nav(pl.read_parquet(folder/'nav.parquet'),label=str(folder))})
        state=json.loads((folder/f"{spec['end'].year}/complete.json").read_text())['state']
        nav=full_nav(state);nav.write_parquet(folder/'full_nav.parquet')
        trades=pl.read_parquet(folder/'trades.parquet');audit=pl.read_parquet(folder/'audit.parquet')
        if nav.filter(pl.col('cash')<-.001).height or trades.select('date','symbol','side').is_duplicated().sum():
            raise ValueError('Cash or duplicate fill invariant failed')
        if any(not b['date'].equals(nav['date']) for b in benchmarks.values()):
            raise ValueError('Registered benchmark and replay full session grids differ')
        metrics=holding_metrics(nav,trades,initial_cash=300000.)
        turn=calendar_turnover(nav,trades)
        rates=fill_evidence(json.loads((folder/'orders.json').read_text()),audit)
        selection=pl.read_parquet(folder/'selection.parquet')
        later=selection.filter(~pl.col('initial_build'))
        if variant=='turnover7_1pct' and later['new_selected'].max()>7:
            raise ValueError('More than seven new selected names after initial construction')
        monthly=trades.with_columns(pl.col('date').dt.strftime('%Y-%m').alias('month')).group_by('month','side').agg(
            pl.col('symbol').n_unique().alias('executed_names'),pl.len().alias('fills'))
        monthly.write_csv(folder/'monthly_executed_names.csv')
        selection_evidence.append(dict(cost_multiplier=cost,signals=selection.height,
            initial=selection.filter(pl.col('initial_build')).to_dicts(),
            maximum_new_selected_after_initial=later['new_selected'].max(),
            maximum_exited_selected=later['exited_selected'].max(),
            total_new_selected_after_initial=later['new_selected'].sum(),
            total_exited_selected=later['exited_selected'].sum(),
            maximum_actual_buy_names_in_month=monthly.filter(pl.col('side')=='BUY')['executed_names'].max(),
            maximum_actual_sell_names_in_month=monthly.filter(pl.col('side')=='SELL')['executed_names'].max(),
            actual_new_position_buy_fills=int(audit['new_position_buy'].sum())))
        row={**metrics,'variant':variant,'cost_multiplier':cost,
            'legacy_252_turnover':metrics['annualized_one_way_turnover'],
            'annualized_one_way_turnover':turn['median'],'calendar_turnover':turn,
            'fill_evidence':rates,'fees':trades['fee'].sum(),'slippage_cost':trades['slippage_cost'].sum(),
            'rejections':pl.read_parquet(folder/'rejections.parquet').group_by('reason').len().sort('reason').to_dicts()}
        rows.append(row);navs[cost]=nav
        for name,b in benchmarks.items():
            reference=path_statistics(b,start=metrics['active_start'],end=spec['end'])
            comparisons.append(dict(variant=variant,cost_multiplier=cost,benchmark=name,
                benchmark_cagr=reference['cagr'],net_cagr_excess=metrics['cagr']-reference['cagr']))
    one=next(r for r in rows if r['cost_multiplier']==1.)
    two=next(r for r in rows if r['cost_multiplier']==2.)
    assessment=assess_model(nav=navs[1.],one=one,two=two,benchmarks=benchmarks,model=model,windows=windows)
    excess=min(r['net_cagr_excess'] for r in comparisons if r['cost_multiplier']==2.)
    assessment['double_cost_excess_strongest']=excess
    assessment['checks']['turnover']=turnover_passes(one['calendar_turnover']['median'],excess)
    assessment['turnover_basis']=one['calendar_turnover']
    assessment['conclusion']='PAPER_CANDIDATE' if all(assessment['checks'].values()) else 'RESEARCH_ONLY' if not assessment['checks']['active_evidence'] else 'REJECTED'
    paired=[];original_sources={}
    for cost in [.5,1.,2.]:
        paths={v:baseline/v/f'cost_{cost:g}'/'full_nav.parquet' for v in ['open_full_fill','limit_1pct']}
        old={v:pl.read_parquet(p) for v,p in paths.items()}
        for p in paths.values():original_sources[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
        start=max([r['active_start'] for r in rows]+[f.filter(pl.col('market_value')>0)['date'].min() for f in old.values()])
        metrics={v:path_statistics(f,start=start,end=spec['end']) for v,f in old.items()}
        current=path_statistics(navs[cost],start=start,end=spec['end'])
        paired.append(dict(cost_multiplier=cost,start=str(start),end=str(spec['end']),diagnostic=current,
            opening_control=metrics['open_full_fill'],original_limit=metrics['limit_1pct'],
            difference_to_open_cagr=current['cagr']-metrics['open_full_fill']['cagr'],
            original_limit_advantage_cagr=metrics['limit_1pct']['cagr']-metrics['open_full_fill']['cagr']))
    result=dict(rows=rows,assessments={variant:assessment},benchmark_comparisons=comparisons,
        paired_comparisons=paired,selection_diagnostics=selection_evidence,reconciliation=guards,
        source=spec['predictions'],original_control_sources_sha256=original_sources,auto_trade=False,
        sample_scope='historical_development_not_unseen_oos',
        measurement='Actual 300k shares; continuous first holding through end, calendar-year median turnover, original three total-return benchmarks',
        interpretation='Seven means new selected names after the first signal; mandatory exits and actual execution can differ. Daily pessimistic veto is fill-feasibility stress, never a signal.',
        pessimistic_advantage_disappeared=(all(r['difference_to_open_cagr']<=0 for r in paired)
            if spec['r4']['kind']=='pessimistic_fill' else None))
    (root/'assessment.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    write_report(root,spec,result)
    if register:
        from quant.reporting.experiment_registry import register_run,records_from_run
        total=register_run(root)
        variants=[r['variant'] for r in records_from_run(root)]
        (root/'registration.json').write_text(json.dumps({'registry_total_rows':total,
            'registered_count':len(variants),'registered_variants':variants}),encoding='utf-8')
    return result


def write_report(root,spec,result):
    variant=spec['scenarios'][0];assessment=result['assessments'][variant]
    lines=['# R4 Top15 单次预注册检验','',f"配置：`{spec['id']}`；实际预注册时刻：{spec['r4']['registered_at']}。",'',
        '冻结R2的30万元、预测、2019起测量区间、原始收盘1%限价、三日原始股数重试、全部费用与三档成本；不改8×门槛。',
        '穿价与20倍额只用于日线成交可行性的悲观诊断，不能用于当日信号选股；仍不能证明订单队列位置或实际可成交。',
        '最大7只定义为首次建仓之后每个信号的新入选成员；原rank/可负担筛选退出不豁免，缺额留现金，不表示最多7个卖单或年换手已≤8×。',
        'A股真实报价单位0.01元：[上交所交易规则§3.3.11](https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml)、[深交所交易规则](https://docs.static.szse.cn/www/lawrules/rule/trade/current/W020260424690713155663.pdf)；冻结执行池均为沪深CNY股票，未把ETF或B股套用股票tick。','',
        '## 三档成本','',
        '| 成本 | 年化 | Sharpe | 最大回撤 | 换手中位/最大 | 股数成交率 | 费用 |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for r in result['rows']:
        t=r['calendar_turnover'];f=r['fill_evidence']['all']
        lines.append(f"| {r['cost_multiplier']:g} | {r['cagr']:.2%} | {r['sharpe']:.3f} | {r['max_drawdown']:.2%} | {t['median']:.3f}/{t['maximum']:.3f} | {f['share_fill_rate']:.2%} | {r['fees']:.2f} |")
    lines+=['','## 与原开盘全成交同窗','',
        '| 成本 | 本情景年化 | 开盘年化 | 本情景减开盘 | 原1%限价减开盘 |',
        '|---|---:|---:|---:|---:|']
    for r in result['paired_comparisons']:
        lines.append(f"| {r['cost_multiplier']:g} | {r['diagnostic']['cagr']:.2%} | {r['opening_control']['cagr']:.2%} | {r['difference_to_open_cagr']:.2%} | {r['original_limit_advantage_cagr']:.2%} |")
    lines+=['','## 原准入门','',f"结论：**{assessment['conclusion']}**；2×相对最强全收益基准超额 {assessment['double_cost_excess_strongest']:.2%}。",'',
        '| 门 | 通过 |','|---|---|']
    lines += [f'| {k} | {v} |' for k,v in assessment['checks'].items()]
    lines+=['','## 成员与实际成交','',
        '| 成本 | 首次入选 | 后续最多新入选 | 最多退出成员 | 单月实际买入/卖出标的最多数 |',
        '|---|---:|---:|---:|---:|']
    for r in result['selection_diagnostics']:
        initial=r['initial'][0]['selected']
        lines.append(f"| {r['cost_multiplier']:g} | {initial} | {r['maximum_new_selected_after_initial']} | {r['maximum_exited_selected']} | {r['maximum_actual_buy_names_in_month']}/{r['maximum_actual_sell_names_in_month']} |")
    lines+=['','## 证据边界','',
        '原R2结果与REJECTED结论不变。新目录记录已见历史上的开发诊断，不是新未见样本外，也不开生产观察账户。',
        '每年execution_inputs保存实际读取的行情、公司行动、官方价格带与日历切片及SHA；成交审计、拒绝、成员变化和原始剩余股数完整保留。',
        'blocked日仍计入原三日重试，不额外延长；20倍阈值使用公司行动后同单位剩余股数乘当前限价。',
        '全日成交额只是悲观容量约束，不等于当时已知全日成交额，更不构成开盘下单信号；模型仍未模拟逐笔队列。',
        '共享账本逐日独立净值核对已复算，结果见assessment.json/reconciliation；没有降低2pp跳变阈值。',
        '未结束的实际观察月份、后续调仓及真钱由各自真实回执和用户决定，本检验不替代。']
    (root/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True)
    p.add_argument('--register',action='store_true')
    args=p.parse_args()
    result=build(args.root,register=args.register)
    print(json.dumps({k:dict(conclusion=v['conclusion'],double_cost_excess=v['double_cost_excess_strongest'])
        for k,v in result['assessments'].items()}))
