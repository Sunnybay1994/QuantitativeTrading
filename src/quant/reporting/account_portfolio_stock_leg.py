"""Report the completed 300k Q10 leg on its continuous invested interval."""
import argparse
import hashlib
import json
from pathlib import Path

import polars as pl

from quant.research.factor_battery_costs import cost_metrics


def build(root: Path):
    status=json.loads((root/'stock_leg_status.json').read_text(encoding='utf-8'))
    if status['status']!='stock_leg_complete' or len(status['rows'])!=3:
        raise ValueError('Require all three completed stock cost replays')
    rows=[]
    for item in status['rows']:
        folder=root/f'cost_{item["cost_multiplier"]:g}'
        nav=pl.read_parquet(folder/'nav.parquet').filter(pl.col('date')>=pl.lit(item['active_start']).str.to_date())
        trades=pl.read_parquet(folder/'trades.parquet')
        measured=cost_metrics(nav,trades,initial_cash=300000.)
        annual=[]
        prior=300000.
        for year in sorted(set(nav['date'].dt.year())):
            chunk=nav.filter(pl.col('date').dt.year()==year)
            equity=chunk['equity'][-1]
            annual.append({'year':year,'return':equity/prior-1,'last_date':str(chunk['date'][-1])})
            prior=equity
        rows.append({'cost_multiplier':item['cost_multiplier'],'active_start':item['active_start'],
            **measured,'annual':annual,'worst_year':min(annual,key=lambda row:row['return']),
            'nav_sha256':hashlib.sha256((folder/'nav.parquet').read_bytes()).hexdigest(),
            'trades_sha256':hashlib.sha256((folder/'trades.parquet').read_bytes()).hexdigest()})
    result={'capital_cny':300000,'rows':rows,'account_portfolio_replayed':False,
            'scope':'Frozen stock leg only; no fixed or risk-parity portfolio admission yet'}
    (root/'diagnostics.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    lines=['# R1 Q10 30万元股票腿', '',
        '原预测、Top50/75与0.5月度换手预算，真实整数股、连续账户；保留首持仓前现金期，指标从2019-01-02持仓起算。', '',
        '2026年仅至8月31日；年度切片不年化。此为股票腿基准，尚非R1两项组合结果。', '',
        '| 成本 | 年化 | Sharpe | 最大回撤 | 最差年度切片 | 切片收益 |', '|---|---:|---:|---:|---:|---:|']
    for row in rows:
        lines.append(f"| {row['cost_multiplier']:g} | {row['cagr']:.2%} | {row['sharpe']:.3f} | "
            f"{row['max_drawdown']:.2%} | {row['worst_year']['year']} | {row['worst_year']['return']:.2%} |")
    (root/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    result=build(parser.parse_args().root)
    print(json.dumps({'rows':len(result['rows']),'account_portfolio_replayed':False}))
