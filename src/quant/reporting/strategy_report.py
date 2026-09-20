"""Combine saved research evidence with the dashboard's 1x period report."""
from html import escape
from pathlib import Path

from quant.reporting.dashboard_curves import catalog, period_report
from quant.reporting.period_metrics import render_html


def render(root: Path, run: str, variant: str, *, entries: list[dict] | None = None) -> str:
    entries = catalog(root) if entries is None else entries
    matches = [e for e in entries if e['kind'] == 'strategy'
               and Path(e.get('run_path', '')).resolve() == (root/run).resolve()
               and e.get('variant') == variant and e.get('cost_multiplier') == 1.]
    if len(matches) != 1:
        raise ValueError('该策略尚无唯一的已保存 1× 净值，请查看原始报告。')
    strategy = matches[0]
    references = [e for e in entries if e['kind'] == 'benchmark'
                  and e.get('code') == 'H00905.CSI' and e['currency'] == strategy['currency']]
    report = period_report([strategy, *references])
    benchmark = references[0]['label']+' / '+references[0]['basis'] if references else ''
    body = render_html(report, benchmark)
    path = (root/strategy['report_path']).resolve()
    if not path.is_relative_to((root/'artifacts').resolve()) or not path.is_file():
        raise ValueError('原始报告路径不可访问')
    original = path.read_text(encoding='utf-8')
    return body + '<h2>原始研究报告（结论与其他成本档保留）</h2><pre>'+escape(original)+'</pre>'
