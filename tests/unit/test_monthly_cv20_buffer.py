import pytest
from quant.research.monthly_cv20_buffer import summarize_cv20_buffer


def rows():
    return [dict(fold=f, comparison=c, cost_multiplier=m, total_return=r,
                 annualized_one_way_turnover=t)
            for f in (1, 2, 3)
            for c, m, r, t in [('top50', 1, .12, 7), ('top50', 2, .08, 7), ('cv20_unbuffered', 1, .10, 10)]]


def test_buffer_admission_uses_paired_compounds():
    result = summarize_cv20_buffer(rows())
    assert result['passed']
    assert result['excess_return_1x'] == pytest.approx(1.12**3 - 1.1**3)


def test_negative_single_cost_return_does_not_pass_on_relative_improvement():
    sample = rows()
    for row in sample:
        if row["comparison"] == "cv20_unbuffered":
            row["total_return"] = -.10
        elif row["cost_multiplier"] == 1:
            row["total_return"] = -.05
    assert summarize_cv20_buffer(sample)["passed"] is False


@pytest.mark.parametrize('change', ['equal_turnover', 'higher_turnover', 'equal_return', 'zero_stress', 'missing_pair'])
def test_buffer_rejects_failed_fixed_conditions(change):
    sample = rows()
    if change == 'missing_pair':
        with pytest.raises(ValueError):
            summarize_cv20_buffer(sample[:-1])
        return
    if change in ('equal_turnover', 'higher_turnover'):
        sample[0]['annualized_one_way_turnover'] = 10 if change == 'equal_turnover' else 11
    if change == 'equal_return':
        for row in sample:
            if row['comparison'] == 'top50' and row['cost_multiplier'] == 1:
                row['total_return'] = .1
    if change == 'zero_stress':
        for row in sample:
            if row['cost_multiplier'] == 2:
                row['total_return'] = 0
    assert not summarize_cv20_buffer(sample)['passed']
