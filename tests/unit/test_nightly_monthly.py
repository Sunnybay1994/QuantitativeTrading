import datetime as dt
import json
import shutil
import sys
import types
from pathlib import Path

import pytest
import polars as pl

from quant.research import nightly_monthly as monthly


def settings(tmp_path):
    return {'output_root': str(tmp_path/'nightly'), 'monthly_first_period': '2026-10',
            'as_of': dt.date(2026, 9, 30), 'data_root': 'data'}


def test_deployment_month_skips_without_touching_model_inputs(tmp_path):
    result = monthly.run_monthly(settings(tmp_path), tmp_path/'2026-09-14')
    assert result['skipped'] is True
    assert not (tmp_path/'nightly').exists()


@pytest.mark.parametrize(('day', 'expected'), [('2026-10-02', None), ('2026-10-03', '2026-10'),
    ('2026-10-04', '2026-10'), ('2026-10-29', '2026-10')])
def test_first_saturday_unlocks_every_subsequent_night(tmp_path, day, expected):
    assert monthly.due_period(settings(tmp_path), dt.date.fromisoformat(day)) == expected


def test_missed_entire_month_catches_up_before_next_saturday(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(monthly, '_run_month', lambda spec, path: calls.append((spec, path)) or {'completed': True})
    monthly.monthly_models(settings(tmp_path), tmp_path/'2026-11-01')
    assert calls[0][1].name == '2026-10'
    assert calls[0][0]['as_of'] == dt.date(2026, 9, 30)


def test_completed_month_is_reused(tmp_path, monkeypatch):
    spec = settings(tmp_path)
    folder = Path(spec['output_root'])/'monthly/2026-10'
    folder.mkdir(parents=True)
    (folder/'summary.json').write_text(json.dumps({'completed': True, 'period': '2026-10'}))
    monkeypatch.setattr(monthly, '_run_month', lambda *_: pytest.fail('Completed month must not rerun'))
    assert monthly.monthly_models(spec, tmp_path/'2026-10-14')['completed']
    assert monthly.pending_month(spec, tmp_path/'2026-10-14') is None


def test_scheduler_prioritizes_incomplete_month_on_weekday(tmp_path):
    spec = settings(tmp_path)
    folder = Path(spec['output_root'])/'monthly/2026-10'
    folder.mkdir(parents=True)
    (folder/'request.json').write_text('{}')
    assert monthly.pending_month(spec, tmp_path/'2026-10-05') == '2026-10'


def test_incomplete_stage_is_preserved_and_completed_stage_reused(tmp_path):
    stage = tmp_path/'predictions'
    stage.mkdir()
    (stage/'partial.txt').write_text('prior attempt')
    def action():
        stage.mkdir()
        (stage/'result.parquet').write_text('done')
        (stage/'summary.json').write_text('{"completed": true}')
        return {'completed': True}
    assert monthly._stage(stage, action, ('result.parquet',))['completed']
    assert len(list(tmp_path.glob('predictions_partial_*/partial.txt'))) == 1
    assert monthly._stage(stage, lambda: pytest.fail('Already complete'), ('result.parquet',))['completed']


def test_freeze_keeps_formal_library_and_configuration_across_retry(tmp_path, monkeypatch):
    import tomllib
    source = Path('configs/factors/library')
    library = tmp_path/'library'
    library.mkdir()
    base, auto = sorted(source.glob('*.toml'))[:2]
    shutil.copyfile(base, library/base.name)
    (library/'auto').mkdir()
    shutil.copyfile(auto, library/'auto'/auto.name)
    # Invalid rejected batch must never enter the formal model family.
    rejected = tmp_path/'batches/rejected/library'
    rejected.mkdir(parents=True)
    (rejected/'bad.toml').write_text('invalid rejected candidate')
    helper = types.ModuleType('quant.data.nightly_month_inputs')
    helper.ensure_nightly_month_inputs = lambda **kwargs: kwargs['settings']
    monkeypatch.setitem(sys.modules, 'quant.data.nightly_month_inputs', helper)
    spec = {**settings(tmp_path), 'library': str(library), 'batch_root': str(tmp_path/'batches'),
        'history_start': dt.date(2010, 1, 1), 'workers': 1,
        'model_config': 'configs/models/p4_annual_walk_forward_20260911.toml',
        'constrained_config': 'configs/portfolio/r4_constrained_q10_20260913.toml',
        'measurement_config': 'configs/models/q1_report_measurement_20260912.toml',
        'return_benchmark_config': 'configs/data/return_benchmarks_q1b_20260912.toml',
        'battery_config': 'configs/factors/battery.toml',
        'refresh_config': 'configs/data/refresh_q2_sue_v2_model_20260912.toml'}
    output = tmp_path/'monthly/2026-10'
    frozen = monthly._freeze(spec, output)
    assert frozen['candidate_count'] == 2
    model = tomllib.loads((output/'model.toml').read_text(encoding='utf-8'))
    assert model['walk_forward']['test_end'] == dt.date(2026, 9, 30)
    assert model['selection']['candidate_library'] == 'all_registered_factors_reassessed_at_each_refit'
    assert model['research']['cost_runs'] == []
    assert model['models']['methods'] == ['equal_z', 'positive_mean_ic', 'lightgbm']
    before = (output/'model.toml').read_bytes()
    repeated = monthly._freeze({**spec, 'as_of': dt.date(2026, 10, 30), 'model_config': 'missing'}, output)
    assert repeated == frozen
    assert (output/'model.toml').read_bytes() == before


def test_causal_stage_order_requires_complete_selection(tmp_path, monkeypatch):
    from quant.research import monthly_prefix_costs
    monkeypatch.setattr(monthly_prefix_costs, 'prepare_costs', lambda o, d, c: [Path(p) for p in c.values()])
    from quant.research import model_training_prefix, model_training_costs, model_training_selection
    from quant.research import run_multifactor_predictions
    folder = tmp_path/'evaluation/costs'
    folder.mkdir(parents=True)
    (folder/'batch_summary.json').write_text(json.dumps({'completed_runs': {'factor_a': 'saved/costs'}}))
    calls = []
    monkeypatch.setattr(monthly, '_stage', lambda folder, action, required: action())
    monkeypatch.setattr(model_training_prefix, 'run_prefixes', lambda **kwargs: calls.append('known_prefixes') or {})
    def costs(**kwargs):
        calls.append('prefix_costs')
        assert kwargs['cost_runs'] == [Path('saved/costs')]
        return {}
    monkeypatch.setattr(model_training_costs, 'run_cost_prefixes', costs)
    monkeypatch.setattr(model_training_selection, 'run_selection', lambda **kwargs:
        calls.append('annual_selection') or {'annual_selection': [{'selection_complete': False}]})
    monkeypatch.setattr(run_multifactor_predictions, 'run_predictions', lambda **kwargs: pytest.fail('Incomplete selection trained'))
    with pytest.raises(ValueError, match='causal selection'):
        monthly._predict(tmp_path, Path('data'))
    assert calls == ['known_prefixes', 'prefix_costs', 'annual_selection']


def test_monthly_prefix_costs_load_frozen_return_indexes(tmp_path, monkeypatch):
    from quant.research import monthly_prefix_costs
    monkeypatch.setattr(monthly_prefix_costs, 'prepare_costs', lambda o, d, c: [Path(p) for p in c.values()])
    """The index measurement config is not the return-benchmark source contract."""
    from quant.research import model_training_prefix, model_training_costs, model_training_selection
    from quant.research.factor_battery_cost_report import return_indexes, REQUIRED_BENCHMARKS
    from quant.data import equal_weight_index

    folder = tmp_path/'evaluation/costs'
    folder.mkdir(parents=True)
    (folder/'batch_summary.json').write_text('{"completed_runs": {}}')
    for name, source in (
        ('measurement.toml', 'configs/models/q1_report_measurement_20260912.toml'),
        ('return_benchmarks.toml', 'configs/data/return_benchmarks_q1b_20260912.toml'),
    ):
        shutil.copyfile(source, tmp_path/name)
    monkeypatch.setattr(monthly, '_stage', lambda folder, action, required: action())
    monkeypatch.setattr(model_training_prefix, 'run_prefixes', lambda **kwargs: {})
    dates = [dt.date(2025, 12, day) for day in (29, 30, 31)]
    monkeypatch.setattr(equal_weight_index, 'available_sessions', lambda *_: dates)
    monkeypatch.setattr(equal_weight_index, 'read_etf_total_return', lambda **_: pl.DataFrame({
        'date': dates, 'unit_nav': [1., 1.01, 1.02]}))
    monkeypatch.setattr(equal_weight_index, 'read_equal_weight_index', lambda **_: pl.DataFrame({
        'date': dates, 'daily_return': [0., .01, .01]}))

    def costs(**kwargs):
        indexes = return_indexes(config=kwargs['return_benchmark_config'], data_root=Path('data'),
            start=dt.date(2025, 12, 29), end=dt.date(2025, 12, 31), cache={})
        assert set(indexes) == REQUIRED_BENCHMARKS
        assert all(frame['date'][-1] == dt.date(2025, 12, 31) for frame in indexes.values())
        return {}

    monkeypatch.setattr(model_training_costs, 'run_cost_prefixes', costs)
    monkeypatch.setattr(model_training_selection, 'run_selection', lambda **kwargs:
        {'annual_selection': [{'selection_complete': False}]})
    with pytest.raises(ValueError, match='causal selection'):
        monthly._predict(tmp_path, Path('data'))


def test_construction_dispatch_preserves_budget_and_uses_actual_state_for_r4():
    seen = []
    def constrain(batch, state):
        seen.append(state)
        return batch.with_columns(pl.lit(.01).alias('weight')), {'constraints_satisfied': True}
    dispatch = monthly.construction_dispatch(constrain, 'p4_equal_z_top50')
    batch = pl.DataFrame({'strategy': ['p4_equal_z_top50'], 'weight': [.02]})
    state = {'holdings': {'000001.SZ': {'quantity': 100}}}
    unchanged, info = dispatch(batch, state)
    assert unchanged.equals(batch) and not info['applied'] and not seen
    changed, _ = dispatch(batch.with_columns(pl.lit('p4_equal_z_top50_r4').alias('strategy')), state)
    assert changed['weight'][0] == .01 and seen[0] is state
    with pytest.raises(ValueError, match='Unknown'):
        dispatch(batch.with_columns(pl.lit('other').alias('strategy')), state)
