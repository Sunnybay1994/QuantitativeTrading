import json
from pathlib import Path

import polars as pl
import pytest

from quant.reporting import multifactor_models as reports
from quant.research.factor_battery_cost_report import compare_nav
from tests.unit.test_multifactor_assessment import fixture


def test_report_writes_three_models_and_requires_full_grid_for_double_cost(tmp_path, monkeypatch):
    nav, one, baselines, model, _ = fixture()
    run, benchmark, output = tmp_path/'run', tmp_path/'benchmark', tmp_path/'report'
    run.mkdir()
    source = Path('configs/models/p4_annual_walk_forward_20260911.toml').read_text(encoding='utf-8')
    (run/'model.toml').write_text(source.replace('test_start = 2015-01-01', 'test_start = 2020-01-01').replace(
        'test_end = 2026-08-31', 'test_end = 2024-12-31'), encoding='utf-8')
    (run/'battery.toml').write_text("[run]\nas_of = 2024-12-31\n[data]\netf_total_return_snapshot = 'fixture'\n")
    rows = [{**one, 'variant': f'{method}_top{top}', 'cost_multiplier': cost, 'mean_invested_fraction': 1.}
            for method in model['models']['methods'] for top in (50, 100) for cost in (.5, 1., 2.)]
    (run/'summary.json').write_text(json.dumps({'factor': model['research']['id'], 'rows': rows}, default=str))
    comparisons = [{'variant': row['variant'], 'cost_multiplier': row['cost_multiplier'],
                     'benchmark': name, **compare_nav(nav, baseline)}
                    for row in rows for name, baseline in baselines.items()]
    monkeypatch.setattr(reports, 'available_sessions', lambda root, end: tuple(nav['date']))
    monkeypatch.setattr(reports, 'read_etf_total_return', lambda **kwargs: baselines['510300_total_return_reference'])
    monkeypatch.setattr(reports, 'collect_cost_report', lambda **kwargs: {'rows': rows, 'benchmark_comparisons': comparisons})

    def history(folder, variant, cost, end):
        return (nav if folder == run else baselines[variant]), pl.DataFrame()

    monkeypatch.setattr(reports, 'load_cost_history', history)
    result = reports.report_models(run=run, benchmarks=benchmark, output=output, data_root=tmp_path)
    assert len(result['conclusions']) == 3
    assert pl.read_parquet(output/'cost_metrics.parquet').height == 18
    assert pl.read_parquet(output/'benchmark_comparisons.parquet').height == 54
    for method in model['models']['methods']:
        report = (output/method/'report.md').read_text(encoding='utf-8')
        assert f'# {method}：PAPER_CANDIDATE' in report
        assert '2024_early_year_selloff' in report

    def missing_cash_start(folder, variant, cost, end):
        if folder == run and variant == 'equal_z_top50' and cost == 2.:
            return nav.slice(1), pl.DataFrame()
        return history(folder, variant, cost, end)

    monkeypatch.setattr(reports, 'load_cost_history', missing_cash_start)
    with pytest.raises(ValueError, match='Every cost scenario'):
        reports.report_models(run=run, benchmarks=benchmark, output=tmp_path/'bad_report', data_root=tmp_path)
    assert not (tmp_path/'bad_report').exists()
