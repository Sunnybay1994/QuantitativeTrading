import datetime as dt

import polars as pl
import pytest

from quant.reporting.risk_factor_attribution import fit_day, lagged_panel, portfolio_decomposition


def test_industry_size_identification_and_exact_return_decomposition():
    panel = pl.DataFrame({'trade_date': [dt.date(2024, 1, 3)]*4,
        'exposure_date': [dt.date(2023, 12, 29)]*4, 'symbol': ['a', 'b', 'c', 'd'],
        'eligible': [True]*4, 'industry_l1': ['one', 'one', 'two', 'two'],
        'log_size': [1., 3., 4., 6.], 'security_return': [.01, .05, -.03, .01]})
    fitted, fit = fit_day(panel, market_return=.01, minimum_symbols=4, minimum_industry_symbols=2)
    assert fit['size_return'] == pytest.approx(.02)
    assert fit['weighted_industry_effect'] == pytest.approx(0.)
    assert fitted['specific_component'].abs().max() < 1e-12
    assert fit['industry_groups'] == 2
    with pytest.raises(ValueError, match='strictly lagged'):
        fit_day(panel.with_columns(pl.col('trade_date').alias('exposure_date')), market_return=.01,
                minimum_symbols=4, minimum_industry_symbols=2)
    renamed, _ = fit_day(panel.with_columns(pl.col('industry_l1').replace({'one': 'z', 'two': 'a'})),
                        market_return=.01, minimum_symbols=4, minimum_industry_symbols=2)
    assert renamed['industry_component'].to_list() == fitted['industry_component'].to_list()


def test_price_gap_is_not_a_one_day_return_and_controls_exclude_same_day():
    days = [dt.date(2024, 1, 2), dt.date(2024, 1, 3), dt.date(2024, 1, 4)]
    bars = pl.DataFrame({'symbol': ['a', 'a'], 'trade_date': [days[0], days[2]], 'close': [10., 11.], 'adj_factor': [1., 1.]})
    controls = pl.DataFrame({'symbol': ['a', 'a'], 'trade_date': [days[0], days[2]],
        'total_market_value': [10., 20.], 'eligible': [True, True], 'industry_l1': ['old', 'new']})
    panel = lagged_panel(bars, controls, days)
    assert panel['security_return'].null_count() == 2
    assert panel['industry_l1'][-1] == 'old'


def test_portfolio_execution_and_unknown_contributions_are_preserved():
    day = dt.date(2024, 1, 3)
    holdings = pl.DataFrame({'date': [day, day], 'symbol': ['a', 'b'],
        'prior_weight': [.5, .4], 'contribution': [.03, -.01]})
    fitted = pl.DataFrame({'trade_date': [day], 'symbol': ['a'], 'security_return': [.04],
        'market_component': [.02], 'common_component': [0.], 'industry_component': [.01],
        'size_component': [.01], 'specific_component': [0.]})
    daily = pl.DataFrame({'date': [day], 'daily_return': [.02], 'residual_contribution': [0.]})
    _, result = portfolio_decomposition(holdings, fitted, daily)
    assert result['execution_difference'][0] == pytest.approx(.01)
    assert result['unmodeled_contribution'][0] == -.01
    assert result['unmodeled_prior_weight'][0] == .4
    assert result['reconciliation_error'].abs().max() < 1e-12


def test_projection_uses_fit_centers_without_refitting_or_inventing_industry():
    panel = pl.DataFrame({'trade_date': [dt.date(2024, 1, 3)]*6,
        'exposure_date': [dt.date(2023, 12, 29)]*6, 'symbol': ['a', 'b', 'c', 'd', 'held', 'unknown'],
        'eligible': [True, True, True, True, False, False],
        'industry_l1': ['one', 'one', 'two', 'two', 'one', 'unseen'],
        'log_size': [1., 3., 4., 6., 5., 10.], 'security_return': [.01, .05, -.03, .01, .5, 1.]})
    original, fit = fit_day(panel, market_return=.01, minimum_symbols=4, minimum_industry_symbols=2)
    extended, projected_fit = fit_day(panel, market_return=.01, minimum_symbols=4,
        minimum_industry_symbols=2, project_outside_universe=True)
    assert fit == projected_fit
    assert extended['symbol'].sort().to_list() == ['a', 'b', 'c', 'd', 'held']
    held = extended.filter(pl.col('symbol') == 'held').row(0, named=True)
    assert held['size_exposure'] == 3.  # Center 2 and scale 1 from eligible sample.
    assert held['size_component'] == pytest.approx(.06)
    assert held['industry_component'] == pytest.approx(.02)
    assert held['specific_component'] == pytest.approx(.41)
    common = extended.filter(pl.col('symbol').is_in(original['symbol'].to_list())).sort('symbol')
    assert common.equals(original.sort('symbol'))
    # Even extreme realized returns on held non-universe stocks cannot change fit.
    _, extreme_fit = fit_day(panel.with_columns(pl.when(pl.col('symbol') == 'held').then(1000.)
        .otherwise(pl.col('security_return')).alias('security_return')), market_return=.01,
        minimum_symbols=4, minimum_industry_symbols=2, project_outside_universe=True)
    assert extreme_fit == fit
