import pytest

from quant.research.classic_monthly_baseline import portfolio_admission_summary, validate_turnover_components


def test_cash_roa_buffer_config_keeps_rank_and_control_fixed():
    import copy
    import tomllib
    from pathlib import Path

    from quant.research.classic_monthly_baseline import validate_cash_roa_buffer

    path = Path(__file__).resolve().parents[2] / "configs/research/b53_cash_roa_buffer100_20260910.toml"
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    validate_cash_roa_buffer(config)
    for section, key, value in (
        ("portfolio", "retention_rank", 75),
        ("portfolio", "top_k", 40),
        ("portfolio", "execution_months", [1, 3, 5, 7, 9, 11]),
        ("financials", "factor_family", "cash_yield"),
        ("admission", "comparison", "three_factor"),
    ):
        changed = copy.deepcopy(config)
        changed[section][key] = value
        with pytest.raises(ValueError, match="B53"):
            validate_cash_roa_buffer(changed)


@pytest.mark.parametrize("factor", ["pit_cash_roa_ttm", "pit_cash_yield_ttm"])
def test_cash_single_factor_and_composition_are_fixed(factor):
    from quant.research.classic_monthly_baseline import validate_cash_factor_components

    names = ["alpha158_std20", "alpha158_roc20", "alpha158_rsv20", factor]
    validate_cash_factor_components([factor], [1], False, factor=factor)
    validate_cash_factor_components(names, [-1, 1, -1, 1], True, factor=factor)
    for invalid_names, directions, composition in (
        (names, [-1, 1, -1, -1], True),
        (names, [-1, 1, -1, 1], False),
        ([factor], [1], True),
    ):
        with pytest.raises(ValueError, match="fixed"):
            validate_cash_factor_components(invalid_names, directions, composition, factor=factor)


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


def test_roe_stability_composition_keeps_fixed_direction_and_paired_pool():
    import copy
    import tomllib
    from pathlib import Path

    from quant.research.classic_monthly_baseline import validate_roe_stability_components

    root = Path(__file__).resolve().parents[2]
    single = tomllib.loads((root / 'configs/research/b55_quarterly_roe_stability_20260910.toml').read_text(encoding='utf-8'))
    config = tomllib.loads((root / 'configs/research/b56_roe_stability_composite_20260910.toml').read_text(encoding='utf-8'))
    validate_roe_stability_components(single)
    validate_roe_stability_components(config)
    for section, key, value in (
        ('factors', 'directions', [-1, 1, -1, 1]),
        ('factors', 'names', single['factors']['names']),
        ('roe_stability_composition', 'eligibility', 'three_factor_only'),
        ('admission', 'comparison', '510300'),
        ('portfolio', 'retention_rank', 100),
        ('portfolio', 'execution_months', [1, 3, 5, 7, 9, 11]),
        ('portfolio', 'top_k', 40),
    ):
        changed = copy.deepcopy(config)
        changed[section][key] = value
        with pytest.raises(ValueError, match='ROE stability'):
            validate_roe_stability_components(changed)


def test_annual_profitability_preregistration_is_fixed():
    import copy
    import tomllib
    from pathlib import Path

    from quant.research.classic_monthly_baseline import validate_annual_profitability

    path = Path(__file__).resolve().parents[2] / 'configs/research/b57_annual_profitability_six_20260910.toml'
    config = tomllib.loads(path.read_text(encoding='utf-8'))
    validate_annual_profitability(config)
    for key, value in [('minimum_components', 6), ('maximum_age_months', 12), ('rank_ties', 'dense'),
                       ('missing_component', 'zero'), ('roe', 'n_income / total_assets')]:
        changed = copy.deepcopy(config)
        changed['annual_profitability'][key] = value
        with pytest.raises(ValueError, match='fixed'):
            validate_annual_profitability(changed)
