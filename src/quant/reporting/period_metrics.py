"""Calendar-period diagnostics from saved daily NAV; never changes admission."""
from __future__ import annotations

from collections import defaultdict
import math
import json
from pathlib import Path
from html import escape

import numpy as np
import polars as pl

NOTE = ('收益与超额为区间累计值，不年化；超额=策略收益−基准收益（百分点）。'
        '夏普按日收益、252日年化、无风险利率0%计算；2%为固定利率敏感性，并非历史利率。'
        '最大回撤含期初净值，按每个期间重新计算。短样本夏普不稳定；边界期间未认证为完整年/月。'
        '从首次持仓起含后续现金日；基准缺日或币种不同不计算超额，不填充。')


def period_metrics(nav: pl.DataFrame, benchmarks: dict[str, pl.DataFrame], *,
                   start=None, end=None, initial_nav: float | None = 1.,
                   benchmark_initial_nav: float | None = 1.) -> list[dict]:
    """Each frame has date/unit_nav; returns are computed before date filtering."""
    def daily(frame, initial):
        frame = frame.sort('date')
        if (frame.is_empty() or frame['date'].null_count() or frame['date'].is_duplicated().any()
                or frame['unit_nav'].null_count() or not frame['unit_nav'].is_finite().all()
                or (frame['unit_nav'] <= 0).any()):
            raise ValueError('Period metrics require unique dates and positive finite NAV')
        previous, previous_date, result = initial, None, {}
        for row in frame.to_dicts():
            date, value = row['date'], row['unit_nav']
            result[date] = (value/previous-1 if previous is not None else None, previous_date)
            previous, previous_date = value, date
        return result

    strategy = daily(nav, initial_nav)
    references = {name: daily(frame, benchmark_initial_nav) for name, frame in benchmarks.items()}
    if start is None and 'market_value' in nav.columns:
        held = nav.filter(pl.col('market_value') > 0)
        if held.is_empty():
            return []
        start = held['date'].min()
    dates = [d for d in strategy if (start is None or d >= start) and (end is None or d <= end)]
    if not dates:
        return []
    rows = []
    for frequency, width in [('year', 4), ('month', 7)]:
        groups = defaultdict(list)
        for date in dates:
            groups[str(date)[:width]].append(date)
        for period, grid in groups.items():
            values = [strategy[d][0] for d in grid]
            complete = all(value is not None for value in values)
            returns = np.array(values, dtype=float) if complete else np.array([])
            levels = np.r_[1., np.cumprod(1+returns)]
            deviation = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.
            total = float(levels[-1]-1) if complete else None
            row = {'frequency': frequency, 'period': period, 'start': str(grid[0]), 'end': str(grid[-1]),
                   'sessions': len(grid), 'boundary_period': period in (str(dates[0])[:width], str(dates[-1])[:width]),
                   'total_return': total,
                   'sharpe': float(returns.mean()/deviation*math.sqrt(252)) if deviation > 1e-12 else None,
                   'sharpe_rf2': float((returns.mean()-(1.02**(1/252)-1))/deviation*math.sqrt(252)) if deviation > 1e-12 else None,
                   'max_drawdown': float(np.min(levels/np.maximum.accumulate(levels)-1)) if complete else None,
                   'benchmark_results': []}
            for name, reference in references.items():
                aligned = complete and all(d in reference and reference[d][0] is not None
                    and (reference[d][1] == strategy[d][1]
                         or reference[d][1] is None and benchmark_initial_nav is not None) for d in grid)
                benchmark_return = float(np.prod([1+reference[d][0] for d in grid])-1) if aligned else None
                row['benchmark_results'].append({'benchmark': name, 'total_return': benchmark_return,
                    'excess_return': total-benchmark_return if aligned else None,
                    'status': 'complete' if aligned else 'missing_or_different_sessions'})
            rows.append(row)
    return rows


def render_periods(rows: list[dict]) -> str:
    def fmt(value, percent=True):
        return '不适用' if value is None else format(value, '.2%' if percent else '.3f')
    lines = ['\n## 年度与月度表现', '', NOTE, '']
    if not rows:
        return '\n'.join(lines+['无持仓期，期间指标不适用。', ''])
    for frequency, label in [('year', '年度'), ('month', '月度')]:
        lines += [f'### {label}', '', '|期间|首末日|日数|收益|基准|基准收益|超额|夏普 rf=0|夏普 rf=2%|最大回撤|范围|',
                  '|---|---|---:|---:|---|---:|---:|---:|---:|---:|---|']
        for row in rows:
            if row['frequency'] != frequency:
                continue
            for benchmark in row['benchmark_results'] or [{'benchmark': '未选基准', 'total_return': None, 'excess_return': None}]:
                lines.append(f"|{row['period']}|{row['start']}—{row['end']}|{row['sessions']}|{fmt(row['total_return'])}|"
                    f"{benchmark['benchmark']}|{fmt(benchmark['total_return'])}|{fmt(benchmark['excess_return']).replace('%', 'pp')}|"
                    f"{fmt(row['sharpe'], False)}|{fmt(row['sharpe_rf2'], False)}|{fmt(row['max_drawdown'])}|"
                    f"{'边界期间' if row['boundary_period'] else '区间内'}|")
        lines.append('')
    return '\n'.join(lines)


def write_period_reports(folder: Path, rows: list[dict], description: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder/'metrics.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    annual = render_periods([r for r in rows if r['frequency'] == 'year'])
    links = []
    for year in sorted({r['period'][:4] for r in rows}):
        name = f'monthly_{year}.md'
        monthly = [r for r in rows if r['frequency'] == 'month' and r['period'].startswith(year)]
        (folder/name).write_text(f'# {year} 月度表现\n\n{description}\n'+render_periods(monthly), encoding='utf-8')
        links.append(f'- [{year} 月度明细]({name})')
    (folder/'report.md').write_text(f'# 策略期间表现\n\n{description}\n'+annual+'\n'+'\n'.join(links)+'\n', encoding='utf-8')


def render_html(report: dict, benchmark: str = '') -> str:
    """Download the same rows shown on the dashboard, using its chosen benchmark."""
    def fmt(value, percentage=True):
        return '—' if value is None else format(value*100 if percentage else value, '.2f' if percentage else '.3f')
    html = ['<!doctype html><meta charset="utf-8"><title>策略期间报告</title>',
            '<style>body{font:14px sans-serif;margin:32px}table{border-collapse:collapse;width:100%}'
            'td,th{border:1px solid #ddd;padding:7px;text-align:right}pre{white-space:pre-wrap}</style>',
            '<h1>'+escape(report['label'])+'</h1>', '<p>'+escape(report['description'])+'</p>',
            '<p>原回测初始资金：'+escape(str(report.get('capital') or '未提供')+' '+report['currency'])+'</p>',
            '<p>'+escape(report['note']+' '+'；'.join(report['excluded']))+'</p>',
            '<p>基准：'+escape(benchmark or '未选可比基准')+'。期间诊断不改变原准入结论。</p>']
    for frequency, label in [('year', '年度'), ('month', '月度')]:
        html += ['<h2>'+label+'</h2><table><tr>'+''.join('<th>'+s+'</th>' for s in
                 ['期间', '首末日', '日数', '收益 %', '基准收益 %', '超额 pp', '夏普 rf=0', '夏普 rf=2%', '最大回撤 %', '范围'])+'</tr>']
        for row in report['rows']:
            if row['frequency'] != frequency:
                continue
            reference = next((r for r in row['benchmark_results'] if r['benchmark'] == benchmark), {})
            values = [row['period'], row['start']+'—'+row['end'], str(row['sessions']), fmt(row['total_return']),
                      fmt(reference.get('total_return')), fmt(reference.get('excess_return')),
                      fmt(row['sharpe'], False), fmt(row['sharpe_rf2'], False), fmt(row['max_drawdown']),
                      ('边界期间' if row['boundary_period'] else '区间内')+
                      (' / 基准缺口' if reference and reference['status'] != 'complete' else '')]
            html.append('<tr>'+''.join('<td>'+escape(v)+'</td>' for v in values)+'</tr>')
        html.append('</table>')
    html.append('<h2>来源</h2><pre>'+escape('\n'.join(report['sources']))+'</pre>')
    return '\n'.join(html)
