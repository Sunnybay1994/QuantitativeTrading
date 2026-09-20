from pathlib import Path

import pytest

from quant.reporting import strategy_report as module


def test_combines_same_dashboard_periods_and_original(tmp_path, monkeypatch):
    source = tmp_path/'artifacts/run/report.md'
    source.parent.mkdir(parents=True)
    source.write_text('RESEARCH_ONLY <script>bad</script>', encoding='utf-8')
    strategy = dict(kind='strategy', run_path=str(source.parent), variant='capital_1000000',
                    cost_multiplier=1., report_path=str(source), currency='CNY')
    benchmark = dict(kind='benchmark', code='H00905.CSI', currency='CNY',
                     label='中证500', basis='全收益指数')
    monkeypatch.setattr(module, 'catalog', lambda root: [strategy, benchmark])
    seen = []
    monkeypatch.setattr(module, 'period_report', lambda specs: seen.extend(specs) or {'rows': []})
    monkeypatch.setattr(module, 'render_html', lambda report, benchmark: '年度/月度 '+benchmark)
    result = module.render(tmp_path, str(source.parent), 'capital_1000000')
    assert seen == [strategy, benchmark]
    assert '年度/月度 中证500 / 全收益指数' in result
    assert 'RESEARCH_ONLY &lt;script&gt;' in result
    assert '<script>bad' not in result


def test_missing_nav_does_not_substitute_another_strategy(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'catalog', lambda root: [])
    with pytest.raises(ValueError, match='1×'):
        module.render(tmp_path, 'artifacts/missing', 'budgeted')


def test_external_original_report_rejected(tmp_path, monkeypatch):
    strategy = dict(kind='strategy', run_path=str(tmp_path), variant='v', cost_multiplier=1.,
                    report_path=str(Path('/outside/report.md')), currency='CNY')
    monkeypatch.setattr(module, 'catalog', lambda root: [strategy])
    monkeypatch.setattr(module, 'period_report', lambda specs: {})
    monkeypatch.setattr(module, 'render_html', lambda report, benchmark: '')
    with pytest.raises(ValueError, match='路径'):
        module.render(tmp_path, str(tmp_path), 'v')
