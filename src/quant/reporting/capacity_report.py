"""Summarize completed capacity runs and verify realized gross ADV limits."""
import datetime as dt
import json
from pathlib import Path
import tomllib

import polars as pl

from quant.data.factor_panels import available_sessions
from quant.reporting.calendar_turnover import calendar_turnover
from quant.research.factor_battery_cost_report import load_cost_history


def run(output: Path, data_root: Path = Path('data')) -> dict:
    summary = json.loads((output/'summary.json').read_text(encoding='utf-8'))
    config = tomllib.loads((output/'config.toml').read_text(encoding='utf-8'))
    model = tomllib.loads((output/'model.toml').read_text(encoding='utf-8'))
    sessions = available_sessions(data_root, model['walk_forward']['test_end']+dt.timedelta(days=40))
    following = dict(zip(sessions, sessions[1:]))
    checked, maximum = 0, 0.
    for capital in config['initial_capitals']:
        folder = output/f'capital_{capital}'/'budgeted'
        for trades_path in sorted(folder.glob('cost_*/*/trades.parquet')):
            path = trades_path.parent/'constraints.json'
            caps = {}
            for record in json.loads(path.read_text(encoding='utf-8')):
                day = following[dt.date.fromisoformat(record['as_of'])]
                for symbol, cap in record['execution_notional_caps'].items():
                    caps[day, symbol] = cap
            trades = pl.read_parquet(trades_path).group_by('date', 'symbol').agg(pl.col('notional').sum())
            for trade in trades.iter_rows(named=True):
                cap = caps.get((trade['date'], trade['symbol']), 0.)
                if trade['notional'] > cap+1e-6:
                    raise ValueError(f'Executed gross amount exceeds cap: {path} {trade}')
                checked += 1
                maximum = max(maximum, trade['notional']/cap if cap else 0.)
    rows = summary['rows']
    expected = {(c, m) for c in config['initial_capitals'] for m in (.5, 1., 2.)}
    if {(r['initial_capital'], r['cost_multiplier']) for r in rows} != expected or len(rows) != len(expected):
        raise ValueError('Incomplete capital/cost grid')
    measured = []
    for row in rows:
        folder = output/f"capital_{row['initial_capital']}"
        nav, trades = load_cost_history(folder, 'budgeted', row['cost_multiplier'], model['walk_forward']['test_end'])
        turnover = calendar_turnover(nav, trades)
        measured.append({**row, 'variant': f"capital_{row['initial_capital']}",
            'annualized_one_way_turnover': turnover['median'], 'calendar_turnover': turnover})
    rows = measured
    assessment = {'rows': rows, 'source': config['source'], 'conclusion': 'RESEARCH_ONLY',
        'benchmark_comparisons': summary['benchmark_comparisons'],
        'assessments': {r['variant']: {'conclusion': 'RESEARCH_ONLY'} for r in rows},
        'measurement': 'actual_holding_period_returns_and_calendar_median_turnover',
        'execution_check': {'checked_symbol_trade_days': checked, 'violations': 0}}
    (output/'assessment.json').write_text(json.dumps(assessment, default=str, indent=2), encoding='utf-8')
    columns = ['initial_capital', 'cost_multiplier', 'cagr', 'sharpe', 'max_drawdown', 'cumulative_fees', 'trade_count']
    pl.DataFrame([{c: row[c] for c in columns} for row in rows]).write_csv(output/'capacity_curve.csv')
    audit = {'checked_symbol_trade_days': checked, 'maximum_cap_utilization': maximum, 'violations': 0}
    (output/'execution_check.json').write_text(json.dumps(audit, indent=2), encoding='utf-8')
    lines = ['# Q10 容量约束回放', '', '|初始资金|成本倍数|持仓期年化|Sharpe|最大回撤|累计费用|成交笔数|', '|---:|---:|---:|---:|---:|---:|---:|']
    for row in rows:
        lines.append(f"|{row['initial_capital']}|{row['cost_multiplier']}|{row['cagr']:.2%}|{row['sharpe']:.3f}|{row['max_drawdown']:.2%}|{row['cumulative_fees']:.2f}|{row['trade_count']}|")
    lines += ['', f'核对 {checked} 个单证券成交日，超限 0 个，最大额度利用率 {maximum:.2%}。',
        '沿用 Q10 选股及0.5月度换手预算，按信号日ADV20×5%限制实际成交；缺失ADV时不成交，未成交部分等待原月度计划重新计算。',
        '结果属于固定滑点下的容量约束敏感性分析，尚未校准随交易规模变化的市场冲击；不替换现有Q10观察账户。']
    (output/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return audit
