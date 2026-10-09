import datetime as dt
import json
from pathlib import Path
import tomllib

import polars as pl
import pytest

from quant.research.admitted_model_pair import DEFAULT, predict, validate_spec
from quant.research.admitted_model_pair_report import paired_checks
from quant.research.admitted_model_pair_report import common_window_metrics
from quant.research.admitted_model_pair_replay import matched_account_schedule
from quant.research.admitted_model_pair_selection import recompute_family_screen


def test_scope_rejects_more_candidates_or_execution_changes():
    spec = tomllib.loads(DEFAULT.read_text(encoding='utf-8'))
    validate_spec(spec)
    for key, value in (('auto_trade', True), ('capital', 1000000), ('top_k', 6), ('commission_min', 5.)):
        with pytest.raises(ValueError, match='fixed admitted-family'):
            validate_spec({**spec, key: value})
    with pytest.raises(ValueError):
        validate_spec({**spec, 'candidates': spec['candidates']+[spec['candidates'][0]]})


def test_combined_family_fdr_denominator_updates_without_changing_admission():
    table = pl.DataFrame({'factor': ['a', 'b'], 'variant': ['raw', 'raw'], 'p_value': [.02, .5],
                          'statistical_pass': [True, False]})
    cfg = {'multiple_testing': {'q': .05, 'admission_requires_fdr': False}}
    result = recompute_family_screen(table, cfg)
    assert result['bh_adjusted_p'].to_list() == pytest.approx([.04, .5])
    assert result['statistical_pass'].to_list() == [True, False]


def test_gain_cannot_override_risk_gates_or_mismatched_continuous_path():
    control = {1.: {'cagr': .1, 'sharpe_rf2': .7, 'max_drawdown': -.2}, 2.: {'cagr': .05}}
    treatment = {1.: {'cagr': .2, 'sharpe_rf2': .8, 'max_drawdown': -.15}, 2.: {'cagr': .1}}
    result = paired_checks(control, treatment, {'checks': {'turnover': False}}, False)
    assert result['one_cost_cagr_gain'] and result['double_cost_cagr_gain']
    assert not result['original_account_gates'] and not result['same_continuous_session_grid']


def test_matched_grid_excludes_earlier_signal_without_inheriting_holdings():
    dates = [dt.date(2020, 1, day) for day in (2, 3, 6)]
    targets = pl.DataFrame({'as_of': [dt.date(2019, 12, 31), dates[0]],
                           'execution_date': [dates[0], dates[1]]})
    selected, excluded = matched_account_schedule(targets, dates, dates[-1])
    assert selected['as_of'].to_list() == [dates[0]]
    assert excluded['as_of'].to_list() == [dt.date(2019, 12, 31)]


def test_common_measurement_keeps_initial_cash_and_first_return():
    dates = [dt.date(2020, 1, day) for day in (2, 3, 6)]
    nav = pl.DataFrame({'date': dates, 'unit_nav': [1., 1., .9]})
    result = common_window_metrics(nav, dates[0])
    assert result['sessions'] == 3
    assert result['max_drawdown'] == pytest.approx(-.1)
    assert result['cagr'] == pytest.approx(.9**(252/3)-1)


def test_unchanged_ordered_factors_reuse_exact_control_predictions(tmp_path, monkeypatch):
    from quant.data import factor_panels
    from quant.research import model_training_models
    original = tmp_path/'control'; original.mkdir()
    model = '''[research]
statistics_source="unused"
[walk_forward]
test_start=2019-01-01
test_end=2019-12-31
'''
    (original/'model.toml').write_text(model)
    (original/'battery.toml').write_text('start=2010-01-01')
    fits = [{'test_year': 2019, 'factors': ['factor_a'], 'prediction_rows': 1,
             'refit_close': '2018-12-28', 'last_known_exit': '2018-12-03'}]
    (original/'summary.json').write_text(json.dumps({'annual_fits': fits}))
    predictions = pl.DataFrame({'symbol': ['000001.SZ'], 'trade_date': [dt.date(2018, 12, 28)],
                                'lightgbm': [.125], 'test_year': [2019]})
    predictions.write_parquet(original/'monthly_predictions.parquet')
    repair = tmp_path/'repair.toml'
    repair.write_text('[replacements]\n[inputs]\ncalendar_statistics=[]\n[model]\n')
    output = tmp_path/'run'; (output/'selection').mkdir(parents=True)
    (output/'selection/summary.json').write_text(json.dumps({'annual_selection': [{
        'test_year': 2019, 'refit_close': '2018-12-28', 'provisional_selected': ['factor_a']}]}))
    monkeypatch.setattr(factor_panels, 'available_sessions', lambda *_: (dt.date(2018, 12, 28), dt.date(2019, 12, 31)))
    monkeypatch.setattr(model_training_models, 'common_features', lambda **_: pytest.fail('Unchanged fit must not retrain'))
    spec = {'control_predictions': str(original), 'control_model_repair': str(repair), 'candidates': [], 'evidence': 'historical'}
    records = predict(spec, output, data_root=tmp_path)
    assert records[0]['reused_control'] is True
    assert pl.read_parquet(output/'predictions/monthly_predictions.parquet').equals(predictions)
