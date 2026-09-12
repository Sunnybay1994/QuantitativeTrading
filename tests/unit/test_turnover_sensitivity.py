import pytest

from quant.reporting.turnover_sensitivity import threshold_checks


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
