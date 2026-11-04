"""Read completed ETF ledger runs; report descriptive prerequisite evidence."""
import argparse
import json
from pathlib import Path

import polars as pl


def build(root: Path):
    receipt = json.loads((root/'summary.json').read_text(encoding='utf-8'))
    if receipt['status'] != 'complete' or len(receipt['completed']) != 9:
        raise ValueError('Require all three ETFs at all three cost levels')
    rows = []
    split_checks = []
    for item in receipt['completed']:
        folder = Path(item['output'])
        nav = pl.read_parquet(folder/'nav.parquet').sort('date')
        equity = nav['equity']
        prior = 300000.
        annual = []
        for year in sorted(set(nav['date'].dt.year())):
            end = nav.filter(pl.col('date').dt.year() == year)['equity'][-1]
            annual.append({'year': year,'return': end/prior-1})
            prior = end
        rows.append({**item, 'max_drawdown': (equity/equity.cum_max()-1).min(),
            'worst_year': min(annual,key=lambda r:r['return']), 'annual':annual,
            'first_date':str(nav['date'][0]), 'last_date':str(nav['date'][-1]),
            'final_equity':equity[-1]})
        if item['symbol']=='512890.SH':
            split = nav.filter(pl.col('date').cast(pl.String).is_in(['2021-10-21','2021-10-22','2021-10-25']))
            if split.height != 3:
                raise ValueError('Split evidence incomplete')
            before, suspended, resumed = split['equity']
            split_checks.append({'cost_multiplier':item['cost_multiplier'],
                'split_day_equity_unchanged':abs(before-suspended)<1e-6,
                'pre_split_equity':before,'suspended_equity':suspended,'reopening_equity':resumed})
    if not all(row['split_day_equity_unchanged'] for row in split_checks):
        raise ValueError('Split introduced artificial account profit/loss')
    result = {'rows':rows,'split_checks':split_checks,'account_portfolio_replayed':False,
              'scope':'Standalone ETF prerequisites; not the R1 fixed/risk-parity account results'}
    (root/'diagnostics.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    lines=['# R1 ETF 单腿账本验证', '',
        '30万元、季度再平衡、三档成本；使用真实整数份额、现金分红到账和已公告拆分。尚未生成R1两项组合结果。', '',
        '表中年度收益为对应日历年在实际样本内的切片，首尾不足年不年化；2026年仅至8月31日。各ETF区间不同，不能用本表替代R1共同窗口比较。', '',
        '| ETF | 成本 | 最大回撤 | 最差年度切片 | 切片收益 | 末日权益 |', '|---|---:|---:|---:|---:|---:|']
    for row in rows:
        lines.append(f"| {row['symbol']} | {row['cost_multiplier']:g} | {row['max_drawdown']:.2%} | "
            f"{row['worst_year']['year']} | {row['worst_year']['return']:.2%} | {row['final_equity']:.2f} |")
    lines+=['','## 拆分检查','']
    for row in split_checks:
        lines.append(f"- {row['cost_multiplier']:g}倍成本：10-21权益 {row['pre_split_equity']:.2f}，"
            f"10-22权益 {row['suspended_equity']:.2f}，10-25复牌权益 {row['reopening_equity']:.2f}。")
    (root/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args()
    result=build(args.root)
    print(json.dumps({'rows':len(result['rows']),'split_checks':result['split_checks']}))
