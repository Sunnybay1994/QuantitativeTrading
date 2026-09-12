import pytest
import json

from quant.reporting.turnover_sensitivity import threshold_checks, run


def test_relaxing_turnover_does_not_relax_other_checks_or_mutate_original():
    original = {'turnover': False, 'stress_windows': False, 'double_cost_positive': True}
    result = threshold_checks(original, turnover=6.303859, limit=6.5)
    assert result['failed'] == ['stress_windows'] and not result['all_checks_pass']
    assert original['turnover'] is False


def test_exact_limit_and_only_turnover_failure():
    checks = {'turnover': False, 'double_cost_positive': True}
    assert threshold_checks(checks, turnover=6.303859, limit=6.)['all_checks_pass'] is False
    assert threshold_checks(checks, turnover=6.303859, limit=6.5)['all_checks_pass'] is True
    assert threshold_checks(checks, turnover=6., limit=6.)['all_checks_pass'] is True


@pytest.mark.parametrize('turnover,limit', [(float('nan'), 6.), (6., float('inf')), (-1., 6.)])
def test_missing_or_invalid_turnover_is_not_a_pass(turnover, limit):
    with pytest.raises(ValueError):
        threshold_checks({'turnover': False}, turnover=turnover, limit=limit)


def test_current_input_version_counts_exclude_historical_controls(tmp_path):
    config = ['scope = "retrospective_primary_only"', 'auto_trade = false',
              'original_limit = 6.0', 'limits = [6.0, 6.5, 12.0]']
    saved = {}
    for i, (current, stress) in enumerate([(False, True), (True, True), (True, False)]):
        path = tmp_path / f'case{i}.json'
        content = {'primary': {'conclusion': 'REJECTED',
            'checks': {'turnover': False, 'stress_windows': stress}},
            'rows': [{'variant': 'primary', 'cost_multiplier': cost,
                'annualized_one_way_turnover': 6.3, 'cagr': .2} for cost in (.5, 1., 2.)]}
        path.write_text(json.dumps(content))
        saved[path] = path.read_bytes()
        config += ['', '[[candidates]]', f'name = "case{i}"',
            f'current_sue_v2 = {str(current).lower()}',
            'assessment = ' + json.dumps(path.as_posix()), 'assessment_key = "primary"',
            'metrics = ' + json.dumps(path.as_posix()), 'variant = "primary"']
    path = tmp_path / 'config.toml'
    path.write_text('\n'.join(config))
    result = run(config=path, output=tmp_path / 'result')
    assert result['rejected_only_turnover'] == 2
    assert result['current_sue_v2_candidates'] == 2
    assert result['current_sue_v2_only_turnover'] == 1
    assert result['original_decisions_changed'] is False
    assert all(path.read_bytes() == content for path, content in saved.items())
