import json

import pytest

from quant.research.batch_failure_diagnostics import (
    aggregate, diagnose_run, distribution, paired_difference, run_diagnosis,
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
