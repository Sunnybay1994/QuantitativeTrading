import json
from pathlib import Path

import polars as pl
import pytest

from quant.reporting import multifactor_models as reports
from tests.unit.test_multifactor_assessment import fixture


def test_report_writes_three_models_and_requires_full_grid_for_double_cost(tmp_path, monkeypatch):
    nav, one, baselines, model, _ = fixture()
    run, output = tmp_path/'run', tmp_path/'report'
    run.mkdir()
    source = Path('configs/models/p4_annual_walk_forward_20260911.toml').read_text(encoding='utf-8')
    (run/'model.toml').write_text(source.replace('test_start = 2015-01-01', 'test_start = 2020-01-01').replace(
        'test_end = 2026-08-31', 'test_end = 2024-12-31'), encoding='utf-8')
    (run/'battery.toml').write_text("[run]\nas_of = 2024-12-31\n[portfolio]\ninitial_cash = 100.0\n")
    rows = [{**one, 'variant': f'{method}_top{top}', 'cost_multiplier': cost, 'mean_invested_fraction': 1.}
            for method in model['models']['methods'] for top in (50, 100) for cost in (.5, 1., 2.)]
    (run/'summary.json').write_text(json.dumps({'factor': model['research']['id'], 'rows': rows}, default=str))
    coverage = pl.DataFrame({'test_year': [2024, 2024], 'available_stocks': [100, 0],
        'signal_available': [True, False], 'reason': ['available', 'insufficient_complete_feature_rows']})
    coverage.write_parquet(run/'model_signal_coverage.parquet')
    measurement = tmp_path/'measurement.toml'
    measurement.write_text('index_version = "fixture"\nindex_codes = ["H00300.CSI", "H00906.CSI", "H00985.CSI"]\n')
    monkeypatch.setattr(reports, 'available_sessions', lambda root, end: tuple(nav['date']))
    keys = dict(zip(('H00300.CSI', 'H00906.CSI', 'H00985.CSI'), baselines))
    def index(**kwargs):
        key = keys[kwargs['index_code']]
        return baselines[key].select(pl.col('date').alias('trade_date'),
            (pl.col('unit_nav')/pl.col('unit_nav').shift(1).fill_null(1.)-1).alias('daily_return'),
            pl.lit(key).alias('index_name'), pl.lit('total_return').alias('return_type'))
    monkeypatch.setattr(reports, 'read_index_benchmark', index)

    def history(folder, variant, cost, end):
        return nav, pl.DataFrame(schema={'date': pl.Date, 'notional': pl.Float64})

    monkeypatch.setattr(reports, 'load_cost_history', history)
    result = reports.report_models(run=run, measurement_config=measurement, output=output, data_root=tmp_path)
    assert len(result['conclusions']) == 3
    assert pl.read_parquet(output/'cost_metrics.parquet').height == 18
    assert pl.read_parquet(output/'benchmark_comparisons.parquet').height == 54
    assert pl.read_parquet(output/'model_signal_coverage.parquet').equals(coverage)
    for method in model['models']['methods']:
        report = (output/method/'report.md').read_text(encoding='utf-8')
        assert f'# {method}：PAPER_CANDIDATE' in report
        assert '2024_early_year_selloff' in report
        assert '|2024|2|1|共同预测截面不足=1|' in report

    saved_metrics = pl.read_parquet(output/'cost_metrics.parquet')
    (output/'cost_metrics.parquet').unlink()
    resumed = reports.report_models(run=run, measurement_config=measurement, output=output, data_root=tmp_path, resume=True)
    assert resumed == result
    assert pl.read_parquet(output/'cost_metrics.parquet').equals(saved_metrics)
    altered = tmp_path/'altered.toml'
    altered.write_bytes(measurement.read_bytes()+b'\n# changed\n')
    with pytest.raises(ValueError, match='inputs changed'):
        reports.report_models(run=run, measurement_config=altered, output=output, data_root=tmp_path, resume=True)

    constraint_path = run/'constraints_config.toml'
    constraint_path.write_text('strategy_names = ["p4_lightgbm_top50"]\n')
    with pytest.raises(ValueError, match='constraints changed'):
        reports.report_models(run=run, measurement_config=measurement, output=output, data_root=tmp_path, resume=True)
    constrained = tmp_path/'constrained_report'
    reports.report_models(run=run, measurement_config=measurement, output=constrained, data_root=tmp_path)
    assert (constrained/'constraints_config.toml').read_bytes() == constraint_path.read_bytes()
    assert "['p4_lightgbm_top50']" in (constrained/'lightgbm'/'report.md').read_text(encoding='utf-8')
    constraint_path.write_text('strategy_names = ["p4_lightgbm_top100"]\n')
    with pytest.raises(ValueError, match='constraints changed'):
        reports.report_models(run=run, measurement_config=measurement, output=constrained, data_root=tmp_path, resume=True)

    def missing_cash_start(folder, variant, cost, end):
        if folder == run and variant == 'equal_z_top50' and cost == 2.:
            return nav.slice(1), pl.DataFrame(schema={'date': pl.Date, 'notional': pl.Float64})
        return history(folder, variant, cost, end)

    monkeypatch.setattr(reports, 'load_cost_history', missing_cash_start)
    with pytest.raises(ValueError, match='Every cost scenario'):
        reports.report_models(run=run, measurement_config=measurement, output=tmp_path/'bad_report', data_root=tmp_path)
    assert not (tmp_path/'bad_report').exists()
