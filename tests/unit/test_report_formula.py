import pytest

from quant.factors.search import canonical
from quant.research.report_formula import formula_expression


def test_report_cv_population_std_and_alias_are_preserved():
    definition = '`CV20=std(u,20,ddof=0)/mean(u,20)`，`u=turnover_rate/100`；低值优先'
    actual = formula_expression('CV20=std(u,20,ddof=0)/mean(u,20)', definition)
    expected = 'ts_std0(turnover_rate/100,20)/ts_mean(turnover_rate/100,20)'
    assert canonical(actual) == canonical(expected)
    assert canonical(formula_expression('`CV20=std(u,20,ddof=0)/mean(u,20)`，`u=turnover_rate/100`', definition)) == canonical(expected)
    assert canonical(formula_expression('CV20=ts_std0(u,20)/ts_mean(u,20)', definition)) == canonical(expected)


@pytest.mark.parametrize('formula,definition', [
    ('std(volume,20)', ''), ('std(volume,20,ddof=2)', ''),
    ('u', '`u=v`，`v=u`'), ('u', '`u=volume`，`u=adj_close`'),
    ('x=1; y=2', ''), ("__import__('os').system('x')", ''),
])
def test_ambiguous_or_unsafe_formula_fails(formula, definition):
    with pytest.raises(ValueError):
        formula_expression(formula, definition)
