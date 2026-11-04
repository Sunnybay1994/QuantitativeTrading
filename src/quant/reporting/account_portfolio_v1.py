"""Assess and register the two completed preregistered R1 portfolios."""
import argparse
import datetime as dt
import json
from pathlib import Path
import tomllib

import polars as pl

from quant.research.factor_battery_costs import cost_metrics


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


def build(*, root, stock, register=False):
    receipt=json.loads((root/'summary.json').read_text(encoding='utf-8'))
    if receipt['status']!='replayed' or len(receipt['completed'])!=15:
        raise ValueError('Require two complete portfolio families, all controls and proxy costs')
    spec=tomllib.loads((root/'config.toml').read_text(encoding='utf-8'))
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
    (root/'assessment.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    lines=['# R1 账户组合族回放', '',
        '30万元、真实整数持仓及共享现金账本；2019-01-02至2026-08-31，首尾年度收益按实际日历切片，不年化。', '',
        '季度资产配置转移与Q10月度0.5内部换手分开计量；ETF数量非季度保持，分红现金进入共享现金。未上市红利ETF份额留现金。', '',
        '| 组合 | 成本 | 年化 | Sharpe | 最大回撤 | 最差年 | 年收益 | Sharpe增量 | 四门 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---|']
    for row in rows:
        flags=', '.join(f'{k}={v}' for k,v in row['checks'].items())
        lines.append(f"| {row['variant']} | {row['cost_multiplier']:g} | {row['cagr']:.2%} | {row['sharpe']:.3f} | "
            f"{row['max_drawdown']:.2%} | {row['worst_year']['year']} | {row['worst_year']['return']:.2%} | "
            f"{row['sharpe_improvement']:.3f} | {flags} |")
    lines+=['','2×成本年化门只在2×行判定，其他行该门为不适用；其余三门逐档报告。正式门槛未改。',
        '', '## 两个必报悲观情景', '',
        '基础组合已持有国债且没有黄金，黄金换国债为恒等重算，不能称为独立压力损失。',
        '原Q10连续窗口缺少2015、2018熊市；以下以510300全收益代替股票腿，尚未上市的红利低波ETF对应份额保留现金。', '',
        '| 组合 | 成本 | 2015–2018代理年化 | 最大回撤 | 最差年 | 年收益 |', '|---|---:|---:|---:|---:|---:|']
    for key,value in stress.items():
        row=value['proxy_2015_2018']
        lines.append(f"| {key} | 见组合名 | {row['cagr']:.2%} | {row['max_drawdown']:.2%} | "
            f"{row['worst_year']['year']} | {row['worst_year']['return']:.2%} |")
    lines+=['','## 结论','']+[f"- {v}: {a['conclusion']}。" for v,a in assessments.items()]
    lines+=['','## ETF上市与成交额', '',
        '上市日期在预注册固定；逐配置日仅用当时之前60个交易日行情核对成交额，明细见liquidity_diagnostics.parquet。未上市和已公告停牌日不补造行情；本明细为回放后的审计输出，不声称它在回放前已落盘。']
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
    args=p.parse_args()
    result=build(root=args.root,stock=args.stock,register=args.register)
    print(json.dumps({'assessments':result['assessments'],'registered_count':result.get('registered_count')},ensure_ascii=False))
