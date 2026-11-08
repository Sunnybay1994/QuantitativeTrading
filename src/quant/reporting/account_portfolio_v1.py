"""Assess and register the two completed preregistered R1 portfolios."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import tomllib

import polars as pl

from quant.research.factor_battery_costs import cost_metrics


def compare_legacy_jump(root, legacy):
    """Use repaired independent expectations only after verifying identical prior books/flows."""
    from quant.backtest.account_reconciliation import validate_nav
    day = dt.date(2021, 10, 22)
    rows = []
    for cost in (.5, 1., 2.):
        relative = Path('main/fixed_40_30_30')/f'cost_{cost:g}'
        new = pl.read_parquet(root/relative/'nav.parquet')
        old = pl.read_parquet(legacy/relative/'nav.parquet')
        prior = old.filter(pl.col('date') < day).select('date', 'equity')
        if not prior.equals(new.filter(pl.col('date') < day).select('date', 'equity')):
            raise ValueError('Legacy jump comparison requires identical prior NAV')
        columns = ['date', 'symbol', 'side', 'quantity', 'price', 'fee', 'notional', 'slippage_cost']
        flows = [pl.read_parquet(p/relative/'trades.parquet').filter(pl.col('date') <= day)
                 .select(columns).sort(columns) for p in (root, legacy)]
        if not flows[0].equals(flows[1]):
            raise ValueError('Legacy jump comparison has different prior execution flows')
        current = new.filter(pl.col('date') == day)
        old_equity = old.filter(pl.col('date') == day)['equity'].item()
        probe = current.with_columns(pl.lit(old_equity).alias('equity'))
        rejected = False
        try:
            validate_nav(probe, label='legacy 2021-10-22 against independent corrected expectation')
        except ValueError as exc:
            if 'UNEXPLAINED_NAV_JUMP' not in str(exc):
                raise
            rejected = True
        if not rejected:
            raise ValueError('Legacy split jump was not rejected')
        expected = current['reconciliation_expected_equity'].item()
        rows.append({'date': str(day), 'cost_multiplier': cost, 'prior_nav_and_flows_identical': True,
                     'legacy_equity': old_equity, 'corrected_equity': current['equity'].item(),
                     'independent_expected_equity': expected,
                     'legacy_unexplained_return': (old_equity-expected)/current['reconciliation_previous_equity'].item(),
                     'legacy_guard_rejected': rejected, 'new_guard': validate_nav(current)})
    result = {'source_legacy': str(legacy), 'corrected': str(root), 'rows': rows}
    (root/'legacy_jump_comparison.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def assess_gates(rows, limits, *, remove_improvement=False):
    """Keep the Sharpe floor; removing only +0.2 is a non-effective diagnostic."""
    checks = {}
    for row in rows:
        cost = row['cost_multiplier']
        gates = {
            'maximum_drawdown': row['max_drawdown'] >= -limits['maximum_drawdown'],
            'sharpe_and_improvement': row['sharpe'] >= limits['minimum_sharpe'] and (
                remove_improvement or row['sharpe_improvement'] >=
                limits['minimum_sharpe_improvement_over_stock']),
            'worst_calendar_year': row['worst_year']['return'] >= limits['minimum_worst_calendar_year'],
        }
        if cost == 2.:
            gates['double_cost_cagr_over_treasury'] = (
                row['treasury_cagr_excess'] >= limits['minimum_double_cost_cagr_over_treasury'])
        checks.update({f'{key}_{cost:g}x': value for key, value in gates.items()})
    return {'conclusion': 'PAPER_CANDIDATE' if all(checks.values()) else 'REJECTED',
            'checks': checks, 'effective': not remove_improvement}


def measure(path, *, start=None):
    nav=pl.read_parquet(path/'nav.parquet')
    trades=pl.read_parquet(path/'trades.parquet')
    if start is not None:
        nav=nav.filter(pl.col('date')>=start)
        trades=trades.filter(pl.col('date')>=start)
    metrics=cost_metrics(nav,trades,initial_cash=300000.)
    annual=[]
    prior=300000.
    for year in sorted(set(nav['date'].dt.year())):
        selected=nav.filter(pl.col('date').dt.year()==year)
        final=selected['equity'][-1]
        annual.append({'year':year,'return':final/prior-1,'last_date':str(selected['date'][-1])})
        prior=final
    return {**metrics,'annual':annual,'worst_year':min(annual,key=lambda r:r['return']),
        'first_date':str(nav['date'][0]),'last_date':str(nav['date'][-1]),
        'negative_cash_days':nav.filter(pl.col('cash')<-.001).height,
        'duplicate_fills':trades.select('date','symbol').is_duplicated().sum()}


def build(*, root, stock, register=False, zero_alpha=None, legacy=None):
    receipt=json.loads((root/'summary.json').read_text(encoding='utf-8'))
    if receipt['status']!='replayed' or len(receipt['completed'])!=15:
        raise ValueError('Require two complete portfolio families, all controls and proxy costs')
    spec=tomllib.loads((root/'config.toml').read_text(encoding='utf-8'))
    top15=spec.get('stock_variants')==['top15_limit_1pct']
    manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    panel=next(Path(name).parent for name in manifest if Path(name).name=='summary.json')
    bars=pl.read_parquet(panel/'bars.parquet')
    calendar=pl.read_parquet(panel/'calendar.parquet')
    quarter_dates=set()
    for path in root.glob('*/*/cost_*/*/allocation.json'):
        for row in json.loads(path.read_text(encoding='utf-8')):
            if row.get('quarterly_allocation'):
                quarter_dates.add(dt.date.fromisoformat(row['as_of']))
    liquidity=[]
    for day in sorted(quarter_dates):
        dates=calendar.filter(pl.col('is_open') & (pl.col('date')<=day))['date'].unique().sort().tail(60)
        for key in ('dividend','treasury'):
            symbol=spec['etfs'][key]['symbol']
            sample=bars.filter((pl.col('symbol')==symbol)&pl.col('trade_date').is_in(dates.implode()))
            liquidity.append({'as_of':day,'symbol':symbol,'listed':spec['etfs'][key]['listing_date']<=day,
                'quoted_sessions':sample.height,'window_sessions':dates.len(),
                'turnover_cny_median':sample['amount'].median(),'turnover_cny_min':sample['amount'].min()})
    pl.from_dicts(liquidity).write_parquet(root/'liquidity_diagnostics.parquet')
    limits=spec['assessment']
    entries={(r['period'],r['variant'],r['cost_multiplier']):Path(r['path']) for r in receipt['completed']}
    rows,assessments,comparisons,stress=[],{},{},{}
    costs=spec['cost_multipliers']
    treasury={c:measure(entries['main','treasury_only',c]) for c in costs}
    control={c:measure(stock/f'cost_{c:g}',start=spec['start']) for c in costs}
    comparisons=[]
    for variant in spec['variants']:
        checks={}
        for cost in costs:
            row=measure(entries['main',variant,cost])
            if row['negative_cash_days'] or row['duplicate_fills']:
                raise ValueError('Account reconciliation invariant failed')
            if row['first_date']!=str(control[cost]['first_date']) or row['last_date']!=control[cost]['last_date']:
                raise ValueError('Stock comparison dates differ')
            delta=row['sharpe']-control[cost]['sharpe']
            gates={'maximum_drawdown':row['max_drawdown']>=-limits['maximum_drawdown'],
                'sharpe_and_improvement':row['sharpe']>=limits['minimum_sharpe'] and delta>=limits['minimum_sharpe_improvement_over_stock'],
                'double_cost_cagr_over_treasury':None if cost!=2. else row['cagr']>=treasury[cost]['cagr']+limits['minimum_double_cost_cagr_over_treasury'],
                'worst_calendar_year':row['worst_year']['return']>=limits['minimum_worst_calendar_year']}
            checks.update({f'{key}_{cost:g}x':value for key,value in gates.items() if value is not None})
            rows.append({**row,'variant':variant,'cost_multiplier':cost,'checks':gates,
                'active_start':row['first_date'],'report_end':row['last_date'],
                'stock_sharpe':control[cost]['sharpe'],'sharpe_improvement':delta,
                'treasury_cagr':treasury[cost]['cagr'],'treasury_cagr_excess':row['cagr']-treasury[cost]['cagr']})
            comparisons.append({'variant':variant,'cost_multiplier':cost,'benchmark':'511010.SH',
                'benchmark_cagr':treasury[cost]['cagr']})
            stress[variant+f'_{cost:g}x']={'gold_to_treasury':{'method':'identity_no_gold_in_base',
                'cagr':row['cagr'],'max_drawdown':row['max_drawdown'],'explanation':spec['pessimistic']['gold_to_treasury']['explanation']},
                'proxy_2015_2018':measure(entries['proxy_2015_2018',variant,cost])}
        assessments[variant]={'conclusion':'PAPER_CANDIDATE' if all(checks.values()) else 'REJECTED',
            'checks':checks,'strongest_benchmark':'511010.SH',
            'net_cagr_excess':next(r['treasury_cagr_excess'] for r in rows if r['variant']==variant and r['cost_multiplier']==1.)}
    result={'rows':rows,'assessments':assessments,'benchmark_comparisons':comparisons,
        'pessimistic_scenarios':stress,'auto_trade':False,'source':str(stock),
        'measurement':'Continuous 2019 stock interval, quarterly actual-share account, three costs, roadmap account gates'}
    result['diagnostic_without_sharpe_improvement'] = {
        variant: assess_gates([r for r in rows if r['variant'] == variant], limits,
                              remove_improvement=True) for variant in spec['variants']}
    result['diagnostic_rule_status'] = 'Not effective; requires explicit user confirmation; original gates unchanged'
    if top15:
        result.update(stock_rule=spec['stock_rule'],reused_controls=receipt['reused_controls'])
    (root/'assessment.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    lines=['# R1 账户组合族回放', '',
        '30万元、真实整数持仓及共享现金账本；2019-01-02至2026-08-31，首尾年度收益按实际日历切片，不年化。', '',
        '季度资产配置转移与Q10月度0.5内部换手分开计量；ETF数量非季度保持，分红现金进入共享现金。未上市红利ETF份额留现金。', '',
        '| 组合 | 成本 | 年化 | Sharpe | 最大回撤 | 最差年 | 年收益 | Sharpe增量 | 四门 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---|']
    if top15:
        lines[4]='季度配置与Top15月度选股分开；股票按实际分配腿资金筛一手门槛并生成整数股单，固定1%限价最多三会话，共享现金、ETF按开盘成交。ETF非季度保持实际股数，未上市红利ETF留现金；不添加Q10的0.5换手预算。'
    for row in rows:
        flags=', '.join(f'{k}={v}' for k,v in row['checks'].items())
        lines.append(f"| {row['variant']} | {row['cost_multiplier']:g} | {row['cagr']:.2%} | {row['sharpe']:.3f} | "
            f"{row['max_drawdown']:.2%} | {row['worst_year']['year']} | {row['worst_year']['return']:.2%} | "
            f"{row['sharpe_improvement']:.3f} | {flags} |")
    lines+=['','2×成本年化门只在2×行判定，其他行该门为不适用；其余三门逐档报告。正式门槛未改。',
        '', '## 两个必报悲观情景', '',
        '基础组合已持有国债且没有黄金，黄金换国债为恒等重算，不能称为独立压力损失。',
        ('原Top15' if top15 else '原Q10')+'连续窗口缺少2015、2018熊市；以下以510300全收益代替股票腿，尚未上市的红利低波ETF对应份额保留现金。', '',
        '| 组合 | 成本 | 2015–2018代理年化 | 最大回撤 | 最差年 | 年收益 |', '|---|---:|---:|---:|---:|---:|']
    for key,value in stress.items():
        row=value['proxy_2015_2018']
        lines.append(f"| {key} | 见组合名 | {row['cagr']:.2%} | {row['max_drawdown']:.2%} | "
            f"{row['worst_year']['year']} | {row['worst_year']['return']:.2%} |")
    lines+=['','## 结论','']+[f"- {v}: {a['conclusion']}。" for v,a in assessments.items()]
    if top15:
        lines+=['','补充对照使用原R1相同国债及2015–2018代理场景，直接复用已完成账本；来源路径及哈希在manifest.json。原Q10两项结果保留。',
            '1%为预先固定R2主档，没有按组合收益选择限价档；这批仍为历史开发回放，不能替代未来真实调度或执行证据。']
    lines+=['','## ETF上市与成交额', '',
        '上市日期在预注册固定；逐配置日仅用当时之前60个交易日行情核对成交额，明细见liquidity_diagnostics.parquet。未上市和已公告停牌日不补造行情；本明细为回放后的审计输出，不声称它在回放前已落盘。']
    lines += ['', '## 删除 Sharpe 增量 +0.2 门的诊断（未生效）', '',
        '只删除相对股票腿的 +0.2 增量要求，Sharpe≥1及其他原门保留；须用户明确确认才可改变规则。', '',
        '|组合|现行规则|删除增量门诊断|', '|---|---|---|']
    for variant, diagnostic in result['diagnostic_without_sharpe_improvement'].items():
        lines.append(f"|{variant}|{assessments[variant]['conclusion']}|{diagnostic['conclusion']}（未生效）|")
    zero_alpha = Path(zero_alpha) if zero_alpha is not None else root/'zero_alpha'
    if (zero_alpha/'summary.json').exists():
        zero = json.loads((zero_alpha/'summary.json').read_text(encoding='utf-8'))
        if zero.get('status') != 'complete':
            raise ValueError('Zero-alpha comparison is not complete')
        # Both R1 families replace the selector with the same frozen proxy.
        source_spec = tomllib.loads((zero_alpha.parent/'config.toml').read_text(encoding='utf-8'))
        for key in ('capital_cny', 'start', 'end', 'fixed_weights', 'variants',
                    'cost_multipliers', 'costs', 'etfs', 'risk_parity', 'stock_source'):
            if spec[key] != source_spec[key]:
                raise ValueError(f'Zero-alpha comparison has a different allocation input: {key}')
        result['zero_alpha_scenarios'] = str(zero_alpha/'summary.json')
        report_link = Path(os.path.relpath(zero_alpha/'report.md', root)).as_posix()
        lines += ['', '## 零超额情景', '',
            f'[机器结果与费用/不可执行性说明]({report_link})。相同配置的ETF代理与指数参考只计算一次，'
            '两族复用不算独立证据。该情景不是收益下限保证，也不替代策略准入。']
    if legacy is not None:
        result['legacy_jump_comparison'] = compare_legacy_jump(root, Path(legacy))
        lines += ['', '## 旧跳变的真实账本反例', '',
            '[逐成本数值证据](legacy_jump_comparison.json)：核对拆分前净值和至拆分日的全部成交流一致，'
            '再将旧实际权益与新账本独立勾稽期望比较；三档均拒绝旧虚增，修复值均通过。旧目录不修改。']
    (root/'assessment.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    (root/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    if register:
        from quant.reporting.experiment_registry import register_run,records_from_run
        total=register_run(root)
        variants=[r['variant'] for r in records_from_run(root)]
        result['registered_count']=len(variants)
        (root/'registration.json').write_text(json.dumps({'registry_total_rows':total,
            'registered_count':len(variants),'registered_variants':variants}),encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--stock',type=Path,required=True)
    p.add_argument('--register',action='store_true')
    p.add_argument('--zero-alpha',type=Path)
    p.add_argument('--legacy',type=Path)
    args=p.parse_args()
    result=build(root=args.root,stock=args.stock,register=args.register,zero_alpha=args.zero_alpha,
                 legacy=args.legacy)
    print(json.dumps({'assessments':result['assessments'],'registered_count':result.get('registered_count')},ensure_ascii=False))
