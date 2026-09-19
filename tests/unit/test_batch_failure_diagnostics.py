import json

import pytest

from quant.research.batch_failure_diagnostics import (
    aggregate, diagnose_run, distribution, paired_difference, render_report, run_diagnosis,
)


def test_missing_evidence_is_not_zero_or_a_pass():
    values = distribution([None, float('nan'), False, -.1, .3])
    assert values['available'] == 2 and values['missing'] == 3
    assert values['nonpositive'] == 1
    assert values['median'] == pytest.approx(.1)
    assert paired_difference([None, .3], [1, .2])['available'] == 1


def test_partial_battery_is_not_counted_as_rejected(tmp_path):
    (tmp_path/'summary.json').write_text(json.dumps({'steps': {'N3': {'ok': False}}}))
    with pytest.raises(ValueError, match='not completed'):
        diagnose_run(tmp_path)
    with pytest.raises(FileExistsError, match='Preserve existing'):
        run_diagnosis([tmp_path/'other'], tmp_path)


def test_cross_stock_objective_uses_worst_group_not_pooled_ic():
    rows = [{'factor': 'a', 'variant': 'raw', 'statistical_pass': False,
             'statistical_failures': ['hac_t'], 'cost_1_cagr': None,
             'cost_0p5_cagr': .02, 'cost_excess_pass': None}]
    candidates = [{'factor_id': 'a', 'terminal_expression': 'ts_mean(gp_price,20)',
                   'search_objective': 'cross_stock_min_ic_v1',
                   'train': {'mean_ic': -.04}, 'worst_directional_mean_ic': -.01,
                   'maximum_rank_correlation': .2, 'fitness': -.111, 'complexity': 2}]
    settings = {'admission': {}, 'multiple_testing': {'admission_requires_fdr': False}}
    result = aggregate(rows, [], candidates, {'favored_terminals': ['gp_financial']}, settings)
    assert result['objective_components'][0]['signal_component'] == -.01
    assert result['objective_components'][0]['residual_complexity_penalty'] == pytest.approx(.001)
    assert result['candidates_using_favored_family_terminals'] == 0
    assert result['cost_excess_pass'] == 0
    assert result['cost_tiers']['1']['all_market_ew_excess']['available'] == 0
    assert result['paired_cagr_change_0p5_to_1']['missing'] == 1
    assert result['fdr_is_required_for_admission'] is False
    assert result['independent_validation'] is False


def test_predictive_priority_has_primary_secondary_and_no_scalar_fitness():
    rows = [{'factor': 'a', 'variant': 'raw', 'statistical_pass': False,
             'statistical_failures': ['hac_t'], 'cost_excess_pass': False}]
    candidate = {'factor_id': 'a', 'terminal_expression': 'gp_financial',
                 'search_objective': 'predictive_priority_v2', 'train': {'mean_ic': .9},
                 'selection_primary': .012, 'maximum_rank_correlation': .8,
                 'selection_eligible': True, 'selection_reasons': [], 'complexity': 1}
    settings = {'admission': {}, 'multiple_testing': {'admission_requires_fdr': False}}
    summary = aggregate(rows, [], [candidate], {}, settings)
    component = summary['objective_components'][0]
    assert component['signal_component'] == .012
    assert component['maximum_rank_correlation'] == .8
    assert component['selection_eligible'] is True
    assert component['fitness'] is component['correlation_penalty'] is component['residual_complexity_penalty'] is None
    assert summary['scalar_objective_candidates'] == 0
    assert summary['correlation_penalty_exceeds_signal_candidates'] == 0
    report = render_report({'batches': [{'run': 'batch_12/2026-09-20', 'search_trials': 200,
        'training_sample': {'sample_first_signal': '2020-01-01', 'sample_last_signal': '2025-12-01'},
        'as_of': '2026-08-31', 'summary': summary}]})
    assert '0.01200' in report and '0.80000' in report
    assert '不构造标量适应度' in report
    assert '相关性惩罚大于适应度' not in report
    assert '0.90000' not in report


def test_predictive_missing_primary_never_falls_back_to_pooled_mean():
    rows = [{'factor': 'a', 'variant': 'raw'}]
    candidate = {'factor_id': 'a', 'terminal_expression': 'gp_financial',
                 'search_objective': 'predictive_priority_v2', 'train': {'mean_ic': .9}}
    settings = {'admission': {}, 'multiple_testing': {'admission_requires_fdr': False}}
    summary = aggregate(rows, [], [candidate], {}, settings)
    component = summary['objective_components'][0]
    assert component['signal_component'] is None
    assert component['maximum_rank_correlation'] is None
    assert component['selection_eligible'] is None
    assert summary['search_selection']['predictive_priority_v2']['primary']['missing'] == 1
