"""R2 actual-fill evidence, common-window comparisons and unchanged admission."""
import argparse
import json
import math
from pathlib import Path
import tomllib

import polars as pl

from quant.data.equal_weight_index import load_return_benchmarks
from quant.reporting.calendar_turnover import calendar_turnover, turnover_passes
from quant.reporting.cycle_stress import path_statistics
from quant.reporting.multifactor_assessment import assess_model, holding_metrics


def full_nav(state):
    fields=['date','equity','unit_nav','cash','market_value','cumulative_fees','receivable']
    return pl.from_dicts([{k:r[k] for k in fields} for r in state['nav']],infer_schema_length=None).with_columns(
        pl.col('date').str.to_date()).sort('date')


def fill_evidence(orders, audit):
    """Normalize split shares to original order units and reconcile both ledgers."""
    if len({o['id'] for o in orders})!=len(orders):
        raise ValueError('Duplicate original order IDs')
    expected={o['id']:o for o in orders}
    actual={}
    for fill in audit.iter_rows(named=True):
        order=expected[fill['order_id']]
        if (fill['symbol'],fill['side'])!=(order['symbol'],order['side']):
            raise ValueError('Fill identity differs from original order')
        if fill['quantity']<=0 or fill['share_factor']<=0:
            raise ValueError('Invalid normalized fill quantity')
        actual[order['id']]=actual.get(order['id'],0.)+fill['quantity']/fill['share_factor']
    for order in orders:
        filled=order['filled_original_units']
        if not 0<=filled<=order['original_quantity']+1e-6 or not math.isclose(
                actual.get(order['id'],0.),filled,abs_tol=1e-6):
            raise ValueError('Original-share fill ledger does not reconcile')
    result={}
    for side in ('BUY','SELL','all'):
        selected=[o for o in orders if side=='all' or o['side']==side]
        part=audit if side=='all' else audit.filter(pl.col('side')==side)
        denominator=sum(o['original_quantity'] for o in selected)
        reference=part.select((pl.col('quantity')*pl.col('opening')).sum()).item()
        result[side]={'orders':len(selected),'original_shares':denominator,
            'filled_original_shares':sum(o['filled_original_units'] for o in selected),
            'share_fill_rate':sum(o['filled_original_units'] for o in selected)/denominator if denominator else None,
            'full_order_fill_rate':sum(o['status']=='filled' for o in selected)/len(selected) if selected else None,
            'expired_orders':sum(o['status']=='expired' for o in selected),
            'partial_orders':sum(0<o['filled_original_units']<o['original_quantity']-1e-6 for o in selected),
            'matched_quote_gap_to_open':part['signed_gap_to_open'].sum()/reference if reference else None}
    return result


def build(*,root,register=False):
    receipt=json.loads((root/'summary.json').read_text())
    spec=tomllib.loads((root/'config.toml').read_text(encoding='utf-8'))
    expected={(v,c) for v in spec['scenarios'] for c in spec['cost_multipliers']}
    if receipt['status']!='replayed' or len(receipt['completed'])!=9 or {
            (r['variant'],r['cost_multiplier']) for r in receipt['completed']}!=expected:
        raise ValueError('Require all nine completed frozen replays')
    model=tomllib.loads((Path(spec['execution_source'])/'model.toml').read_text(encoding='utf-8'))
    windows=tomllib.loads(Path(model['admission']['stress_windows_config']).read_text(encoding='utf-8'))[
        'cycle_validation']['stress_windows']
    benchmarks=load_return_benchmarks(config=Path(spec['return_benchmark_config']),data_root=Path('data'),
        start=model['walk_forward']['test_start'],end=spec['end'])
    benchmarks['510300_total_return_reference']=benchmarks.pop('510300')
    navs,rows,comparisons={},{},[]
    for variant,cost in sorted(expected):
        folder=root/variant/f'cost_{cost:g}'
        state=json.loads((folder/f"{spec['end'].year}/complete.json").read_text())['state']
        nav=full_nav(state)
        nav.write_parquet(folder/'full_nav.parquet')
        trades=pl.read_parquet(folder/'trades.parquet')
        audit=pl.read_parquet(folder/'audit.parquet')
        if (nav.filter(pl.col('cash')<-.001).height or
                trades.select('date','symbol','side').is_duplicated().sum()):
            raise ValueError('Cash or duplicate-fill invariant failed')
        if not nav['date'].equals(next(iter(benchmarks.values()))['date']):
            raise ValueError('Benchmark and account session grids differ')
        for name,frame in benchmarks.items():
            if not frame['date'].equals(nav['date']):
                raise ValueError(f'Benchmark session grid differs: {name}')
        metrics=holding_metrics(nav,trades,initial_cash=300000.)
        if metrics['active_start'] is None:
            raise ValueError('No holding evidence')
        turn=calendar_turnover(nav,trades)
        orders=json.loads((folder/'orders.json').read_text())
        rates=fill_evidence(orders,audit)
        rejects=pl.read_parquet(folder/'rejections.parquet')
        row={**metrics,'variant':variant,'cost_multiplier':cost,
            'legacy_252_turnover':metrics['annualized_one_way_turnover'],
            'annualized_one_way_turnover':turn['median'],'calendar_turnover':turn,
            'fill_evidence':rates,
            'fees':trades['fee'].sum(),'slippage_cost':trades['slippage_cost'].sum(),
            'rejections':rejects.group_by('reason').len().sort('reason').to_dicts()}
        rows[variant,cost]=row
        navs[variant,cost]=nav
        for name,frame in benchmarks.items():
            baseline=path_statistics(frame,start=metrics['active_start'],end=spec['end'])
            comparisons.append({'variant':variant,'cost_multiplier':cost,'benchmark':name,
                'benchmark_cagr':baseline['cagr'],'net_cagr_excess':metrics['cagr']-baseline['cagr']})
    assessments={}
    for variant in spec['scenarios']:
        one,two=rows[variant,1.],rows[variant,2.]
        assessment=assess_model(nav=navs[variant,1.],one=one,two=two,benchmarks=benchmarks,model=model,windows=windows)
        excess=min(r['net_cagr_excess'] for r in comparisons if r['variant']==variant and r['cost_multiplier']==2.)
        assessment['double_cost_excess_strongest']=excess
        assessment['checks']['turnover']=turnover_passes(one['calendar_turnover']['median'],excess)
        assessment['turnover_basis']=one['calendar_turnover']
        assessment['conclusion']=('PAPER_CANDIDATE' if all(assessment['checks'].values()) else
            'RESEARCH_ONLY' if not assessment['checks']['active_evidence'] else 'REJECTED')
        assessments[variant]=assessment
    q10={}
    for cost in spec['cost_multipliers']:
        folder=Path(spec['q10_control'])/f'budgeted/cost_{cost:g}'
        state=json.loads((folder/f"{spec['end'].year}/account.json").read_text())['account']
        q10[cost]=full_nav(state)
        if not q10[cost]['date'].equals(navs['open_full_fill',cost]['date']):
            raise ValueError('Q10 control has a different full session grid')
    common_start=max([r['active_start'] for r in rows.values()]+[
        nav.filter(pl.col('market_value')>0)['date'].min() for nav in q10.values()])
    paired=[]
    for variant,cost in sorted(expected):
        nav=navs[variant,cost]
        strategy=path_statistics(nav,start=common_start,end=spec['end'])
        opening=path_statistics(navs['open_full_fill',cost],start=common_start,end=spec['end'])
        stock=path_statistics(q10[cost],start=common_start,end=spec['end'])
        paired.append({'variant':variant,'cost_multiplier':cost,'start':common_start,'end':spec['end'],
            'top15':strategy,'q10_top50':stock,'open_control':opening,
            'opportunity_cagr_loss':opening['cagr']-strategy['cagr'],
            'terminal_equity_loss':navs['open_full_fill',cost]['equity'][-1]-nav['equity'][-1],
            'cagr_difference_q10':strategy['cagr']-stock['cagr']})
    result={'rows':list(rows.values()),'assessments':assessments,'benchmark_comparisons':comparisons,
        'paired_comparisons':paired,'common_start':common_start,'auto_trade':False,'source':spec['predictions'],
        'measurement':'Actual 300k shares; first holding to end with later cash; calendar CAGR; original return indexes; calendar median turnover, partial years not extrapolated',
        'sample_scope':'historical_development_not_unseen_oos'}
    (root/'assessment.json').write_text(json.dumps(result,indent=2,default=str,ensure_ascii=False),encoding='utf-8')
    write_report(root,result)
    if register:
        from quant.reporting.experiment_registry import register_run,records_from_run
        total=register_run(root)
        variants=[r['variant'] for r in records_from_run(root)]
        (root/'registration.json').write_text(json.dumps({'registry_total_rows':total,
            'registered_count':len(variants),'registered_variants':variants}),encoding='utf-8')
    return result


def write_report(root,result):
    lines=['# R2 Top15 · 30万元 · 预挂限价','',
        '冻结Q10预测，月末信号、排名15买入/30保留，目标单票≤8%，不加Q10的0.5换手预算；实际未卖出持仓可能使持仓数超过15。',
        '信号收盘锚定1%/3%限价，买向下/卖向上取0.01元，最多3个交易日；部分成交仅重挂原始剩余股数。停牌、涨跌停、整手、结算、流动性、现金约束沿用原账本。',
        '股数与限价按已公告公司行动调整；缺当日行情只作停牌历史估值，不伪造可成交报价。未支持的待成交换股直接报错。',
        'A股0.01元报价规则：[上交所](https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml)、[深交所](https://investor.szse.cn/knowledge/t20200408_575791.html)。',
        '', '## 三档成本及成交', '',
        '| 情景 | 成本 | 年化 | Sharpe | 回撤 | 换手中位/最大 | 股数成交率 | 全成订单率 | 匹配价差 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for row in result['rows']:
        rate=row['fill_evidence']['all'];turn=row['calendar_turnover']
        lines.append(f"| {row['variant']} | {row['cost_multiplier']:g} | {row['cagr']:.2%} | {row['sharpe']:.3f} | "
            f"{row['max_drawdown']:.2%} | {turn['median']:.3f}/{turn['maximum']:.3f} | {rate['share_fill_rate']:.2%} | "
            f"{rate['full_order_fill_rate']:.2%} | {rate['matched_quote_gap_to_open']:.3%} |")
    lines+=['','成交率为成交股数除以初始委托股数，送股按原始股数归一；分买卖、部分成交及到期笔数见assessment.json。',
        '价差为匹配报价相对同次成交日开盘的方向性金额差/开盘名义金额，正数表示更贵；账本经济成交价另含原滑点，手续费另列，均只扣一次。',
        '开盘对照仍受停牌、涨跌停及现金等规则约束，不能将未能执行的开盘订单补成成交。',
        '',f"## 与开盘及Q10 Top50同窗（{result['common_start']}起）",'',
        '| 情景 | 成本 | Top15年化 | 开盘对照年化 | 机会年化损失 | 期末资金损失元 | Q10年化 | Top15-Q10 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for row in result['paired_comparisons']:
        lines.append(f"| {row['variant']} | {row['cost_multiplier']:g} | {row['top15']['cagr']:.2%} | "
            f"{row['open_control']['cagr']:.2%} | {row['opportunity_cagr_loss']:.2%} | {row['terminal_equity_loss']:.2f} | "
            f"{row['q10_top50']['cagr']:.2%} | {row['cagr_difference_q10']:.2%} |")
    lines+=['','机会损失为完整成对路径差，包含后续持仓/现金路径反馈，不能解释为逐笔未成交的纯因果贡献。',
        '两策略均为实际30万元。年化沿用原准入的日历年口径，不能与旧252交易日年化直接相减。',
        '', '## 原准入门槛', '',
        '首持有日至期末含后续空仓；起始2015–2018继承现金历史，不算持股证据。三类全收益基准同窗，择最强者；换手按原日历年中位值，6–8倍须2倍成本超额≥5pp，其余门槛不变。']
    for variant,assessment in result['assessments'].items():
        lines+=['',f"### {variant}: {assessment['conclusion']}", '',
            f"最强基准 {assessment['strongest_benchmark']}；1×超额 {assessment['net_cagr_excess']:.2%}；2×超额 {assessment['double_cost_excess_strongest']:.2%}。",'',
            '| 门 | 通过 |','|---|---|']
        lines += [f'| {key} | {value} |' for key,value in assessment['checks'].items()]
        lines+=['','| 压力窗口 | 适用 | 策略收益 | 基准收益 | 不劣 |','|---|---|---:|---:|---|']
        for row in assessment['stress']:
            strategy=f"{row['model_return']:.2%}" if row['applicable'] else row['reason']
            benchmark=f"{row['benchmark_return']:.2%}" if row['applicable'] else '不适用'
            lines.append(f"| {row['window']} | {row['applicable']} | {strategy} | {benchmark} | {row['not_worse']} |")
    lines+=['','## 证据边界','',
        '这是已见历史上的开发回放，未产生新的未见样本外证据；原预测模型与数据修复选择风险仍在。日线触价无法证明排队位置，原流动性规则之外未模拟逐笔队列。',
        '连续价格诊断保留在同日期01目录，正式结果使用02目录；报价精度修正先于查看性能，没有扩大a或改缓冲区。',
        '原默认回放已做六组逐字节验证及30万元Q10全年174文件哈希一致验证，见top15_limit_default_verification_20261104及top15_default_full_q10_300k_20261104_01。',
        '本报告和指标由代码生成。auto_trade=false；满足候选条件才按清单从11月30日信号开启影子，真钱由用户决定。']
    (root/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--register',action='store_true')
    args=parser.parse_args()
    result=build(root=args.root,register=args.register)
    print(json.dumps({'assessments':{k:{'conclusion':v['conclusion'],'checks':v['checks'],
        'double_cost_excess_strongest':v['double_cost_excess_strongest']} for k,v in result['assessments'].items()}},default=str))
