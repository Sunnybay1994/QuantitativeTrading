import pytest

from quant.research.classic_monthly_baseline import portfolio_admission_summary, validate_turnover_components


def test_exact_b25_and_b27_components_only():
    validate_turnover_components(["turnover_cv20"], [-1])
    names = ["alpha158_std20", "alpha158_roc20", "alpha158_rsv20", "turnover_cv20"]
    validate_turnover_components(names, [-1, 1, -1, -1])
    for invalid_names, directions in ((["turnover_cv20"], [1]), (names, [-1, 1, -1, 1]),
                                      (names[:-1], [-1, 1, -1]), (list(reversed(names)), [-1, 1, -1, -1])):
        with pytest.raises(ValueError, match="fixed"):
            validate_turnover_components(invalid_names, directions)


def results(one=.10, two=.05, comparator=.03, benchmark=.20):
    return [{"fold": f, "comparison": c, "cost_multiplier": m, "total_return": r}
            for f in (1, 2, 3) for c, m, r in (("top50", 1., one), ("top50", 2., two),
                                               ("three_factor", 1., comparator), ("510300", 1., benchmark))]


def test_paired_comparison_does_not_change_default_benchmark_semantics():
    rows = results()
    default = portfolio_admission_summary(rows)
    paired = portfolio_admission_summary(rows, "three_factor")
    assert default["comparison"] == "510300" and default["passed"] is False
    assert default["excess_return_1x"] == pytest.approx(1.1 ** 3 - 1.2 ** 3)
    assert paired["comparison"] == "three_factor" and paired["passed"] is True
    assert paired["excess_return_1x"] == pytest.approx(1.1 ** 3 - 1.03 ** 3)
    with pytest.raises(ValueError, match="actual replay"):
        portfolio_admission_summary(rows, "absent")
    with pytest.raises(ValueError, match="actual replay"):
        portfolio_admission_summary(rows[:-1])


@pytest.mark.parametrize("one,two,comparator", [(0., .05, -.1), (.1, 0., 0.), (.1, -.01, 0.), (.1, .05, .1)])
def test_portfolio_admission_requires_strict_positive_profit_and_excess(one, two, comparator):
    assert portfolio_admission_summary(results(one, two, comparator), "three_factor")["passed"] is False
