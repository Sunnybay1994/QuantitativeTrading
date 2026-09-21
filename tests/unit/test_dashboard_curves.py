from pathlib import Path

import polars as pl
import pytest

from quant.reporting.dashboard_curves import compare, read_curve


def spec(tmp_path: Path, name, dates, values):
    path = tmp_path/(name+'.csv')
    pl.DataFrame({'date':dates,'unit_nav':values}).write_csv(path)
    return dict(id=name,label=name,kind='strategy',currency='CNY',basis='NAV',paths=[str(path)])


def test_common_anchor_preserves_missing_sessions_and_source_values(tmp_path):
    a=spec(tmp_path,'a',['2025-01-01','2025-01-02','2025-01-03','2025-01-04'],[10.,20.,30.,40.])
    b=spec(tmp_path,'b',['2025-01-02','2025-01-04','2025-01-05'],[2.,3.,4.])
    result=compare([a,b])
    assert (result['start'],result['end'])==('2025-01-02','2025-01-04')
    assert [p['value'] for p in result['series'][0]['points']]==[0.,.5,1.]
    assert result['series'][1]['points']==[{'date':'2025-01-02','value':0.},{'date':'2025-01-04','value':.5}]
    with pytest.raises(ValueError,match='共同交易日'):
        compare([a,b],start='2025-01-03')


def test_conflicting_duplicate_nav_is_not_silently_combined(tmp_path):
    a=spec(tmp_path,'a',['2025-01-01','2025-01-01'],[1.,2.])
    with pytest.raises(ValueError,match='日期重复'):
        read_curve(a)


def test_nonfinite_nav_is_rejected(tmp_path):
    a=spec(tmp_path,'a',['2025-01-01','2025-01-02'],[1.,float('nan')])
    with pytest.raises(ValueError,match='非有限值'):
        read_curve(a)


@pytest.mark.parametrize('months,start', [(1,'2026-07-31'), (3,'2026-05-31'),
    (6,'2026-02-28'), (12,'2025-08-31'), (36,'2023-08-31')])
def test_shortcuts_use_latest_common_date_and_calendar_months(tmp_path, months, start):
    dates = ['2023-08-30','2023-08-31','2025-08-31','2026-02-28',
             '2026-05-31','2026-07-31','2026-08-31','2026-09-01']
    a = spec(tmp_path, 'a', dates, [1.]*len(dates))
    b = spec(tmp_path, 'b', dates[:-1], [1.]*(len(dates)-1))
    result = compare([a,b], months=months)
    assert (result['start'], result['end']) == (start, '2026-08-31')


def test_short_history_and_leap_year_shortcuts(tmp_path):
    a = spec(tmp_path, 'a', ['2024-02-28','2024-02-29','2024-03-31'], [1.,1.1,1.2])
    assert compare([a], months=1)['start'] == '2024-02-29'
    assert compare([a], months=12)['start'] == '2024-02-28'
    assert compare([a])['start'] == '2024-02-28'
    with pytest.raises(ValueError, match='时间范围'):
        compare([a], months=2)


def test_period_report_keeps_cross_currency_comparison_unavailable(tmp_path):
    from quant.reporting.dashboard_curves import period_report
    a = spec(tmp_path, 'a', ['2025-12-31', '2026-01-02', '2026-01-05'], [1., .9, .99])
    b = spec(tmp_path, 'b', ['2025-12-31', '2026-01-02', '2026-01-05'], [1., 1., 1.])
    b.update(kind='benchmark', currency='USD')
    result = period_report([a, b], start='2026-01-02')
    assert result['rows'][0]['total_return'] == pytest.approx(-.01)
    assert result['rows'][0]['benchmark_results'] == []
    assert result['excluded']


def test_capacity_catalog_uses_replay_nav_and_preserves_report_metadata(tmp_path):
    from quant.reporting.dashboard_curves import catalog
    run = tmp_path/'artifacts/research/r8'
    run.mkdir(parents=True)
    (run/'battery.toml').write_text('[portfolio]\ninitial_cash = 42\n')
    (run/'config.toml').write_text(
        'initial_capitals = [1000000, 5000000]\nparticipation_limit = 0.05\n'
        'monthly_turnover_budget = 0.5\n'
        'interpretation = "capacity_constrained_fixed_slippage_sensitivity_not_calibrated_market_impact"\n')
    records = []
    for capital in (1000000, 5000000):
        variant = f'capital_{capital}'
        records.append(dict(variant=variant, run_path=str(run), source_run='artifacts/source',
                            experiment_id='r8', config_path=str(run/'config.toml'),
                            report_path=str(run/'report.md'), result_time='2026-09-15'))
        for cost in ('0.5', '1', '2'):
            folder = run/variant/'budgeted'/f'cost_{cost}'/'2025'
            folder.mkdir(parents=True)
            pl.DataFrame({'date':['2025-01-02','2025-01-03'], 'unit_nav':[1.,1.1]}).write_parquet(folder/'nav.parquet')
    registry = tmp_path/'artifacts/registry'
    registry.mkdir()
    pl.DataFrame(records).write_parquet(registry/'experiments.parquet')
    curves = catalog(tmp_path)
    assert len(curves) == 6
    for curve in curves:
        assert curve['capital'] == int(curve['variant'][8:])
        assert f"{curve['capital'] / 10000:g}万元" in curve['label']
        assert curve['run_path'] == str(run.resolve())
        assert curve['report_path'] == str((run/'report.md').resolve())
        assert curve['cost_multiplier'] in (.5, 1., 2.)
        assert '/budgeted/' in curve['paths'][0].replace('\\', '/')
        assert '容量敏感性回放' in curve['description']
        assert read_curve(curve)[-1]['value'] == 1.1


def test_missing_capacity_replay_does_not_fall_back_to_source(tmp_path):
    from quant.reporting.dashboard_curves import catalog
    run = tmp_path/'artifacts/research/r8'
    run.mkdir(parents=True)
    source = tmp_path/'artifacts/source/capital_1000000/cost_1/2025'
    source.mkdir(parents=True)
    pl.DataFrame({'date':['2025-01-02'], 'unit_nav':[2.]}).write_parquet(source/'nav.parquet')
    registry = tmp_path/'artifacts/registry'
    registry.mkdir()
    pl.DataFrame([dict(variant='capital_1000000', run_path=str(run), source_run='artifacts/source',
                       experiment_id='r8', config_path=None, report_path=str(run/'report.md'),
                       result_time='2026-09-15')]).write_parquet(registry/'experiments.parquet')
    assert catalog(tmp_path) == []


def test_report_identity_survives_shared_nav_and_explicit_control_fallback(tmp_path):
    from quant.reporting.dashboard_curves import catalog
    source = tmp_path/'artifacts/source'
    folder = source/'budgeted/cost_1/2025'
    folder.mkdir(parents=True)
    pl.DataFrame({'date':['2025-01-02'], 'unit_nav':[1.]}).write_parquet(folder/'nav.parquet')
    records = []
    for name in ('original', 'remeasured', 'control_reference'):
        run = tmp_path/'artifacts'/name
        run.mkdir()
        (run/'config.toml').write_text('[research]\ncontrol = "artifacts/source"\n')
        records.append(dict(variant='budgeted', run_path=str(run),
                            source_run='artifacts/source' if name != 'control_reference' else '',
                            experiment_id=name, config_path=str(run/'config.toml'),
                            report_path=str(run/'report.md'), result_time='2026-09-15'))
    registry = tmp_path/'artifacts/registry'
    registry.mkdir()
    pl.DataFrame(records).write_parquet(registry/'experiments.parquet')
    curves = catalog(tmp_path)
    assert len(curves) == len({s['id'] for s in curves}) == 3
    assert len({s['report_path'] for s in curves}) == 3
    assert len({tuple(s['paths']) for s in curves}) == 1
