import datetime as dt

import numpy as np
import polars as pl
import pytest

from quant.data.risk_model_inputs import standardize
from quant.risk.model import EWMARisk, STYLES, fit_wls, prepare_exposures, tracking_error
from quant.risk.run import write_stress_window


def test_weighted_cross_section_reconciles_and_is_orthogonal():
    random = np.random.default_rng(72)
    x = np.column_stack([random.normal(size=(150, 10)), np.ones(150)])
    cap = np.exp(random.normal(size=150))
    y = x@random.normal(size=11)+random.normal(size=150)
    beta, residual = fit_wls(x, y, cap)
    np.testing.assert_allclose(x@beta+residual, y, atol=1e-12)
    np.testing.assert_allclose(x.T@(np.sqrt(cap)*residual), 0, atol=1e-10)


def test_risk_prediction_uses_only_prior_updates():
    state = EWMARisk(2, minimum_history=2)
    state.update(dt.date(2024, 1, 1), np.array([.01, -.02]), {'A': .01})
    assert state.covariance() is None
    state.update(dt.date(2024, 1, 2), np.array([-.01, .02]), {'A': -.02})
    before = state.covariance().copy()
    risk = tracking_error(np.array([.5]), np.array([[1., 2.]]), before, np.array([.01]))
    assert risk > 0
    assert state.last_date == dt.date(2024, 1, 2)
    state.update(dt.date(2024, 1, 3), np.array([20., -10.]), {'A': 3.})
    assert not np.allclose(before, state.covariance())
    assert np.linalg.eigvalsh(state.covariance()).min() >= -1e-10
    with pytest.raises(ValueError, match='strictly increasing'):
        state.update(dt.date(2024, 1, 3), np.zeros(2), {})


def test_missing_style_is_disclosed_and_industry_median_not_zero():
    frame = pl.DataFrame({'symbol': ['a', 'b', 'c'], 'industry_l1': ['i', 'i', 'j'],
                          'eligible': [True]*3, **{name: [2., None, 4.] for name in STYLES}})
    result = prepare_exposures(frame).sort('symbol')
    assert result['size'].to_list() == [2., 2., 4.]
    assert result['imputed_styles'].to_list() == [0, 10, 0]


def test_standardization_uses_eligible_sample_and_preserves_missing():
    day = dt.date(2024, 1, 1)
    frame = pl.DataFrame({'trade_date': [day]*4, 'eligible': [True, True, False, False],
                          'size': [1., 3., 10000., None]})
    result = standardize(frame, ['size'])
    np.testing.assert_allclose(result['size'][:2].to_numpy(), [-1., 1.])
    assert result['size'][3] is None


def test_stress_linking_reconciles_compound_return(tmp_path):
    frame = pl.DataFrame({'date': [dt.date(2024, 1, 2), dt.date(2024, 2, 8)],
        'portfolio': ['q10']*2, 'prior_equity': [100., 110.], 'equity': [110., 132.],
        'daily_return': [.1, .2], 'size': [.1, .2],
        **{name: [0., 0.] for name in STYLES if name != 'size'},
        'industry:UNKNOWN': [0., 0.], 'specific': [0., 0.], 'unmodeled': [0., 0.],
        'execution_cost_and_cash_residual': [0., 0.]})
    frame.write_parquet(tmp_path/'daily_attribution.parquet')
    (tmp_path/'report.md').write_text('Report\n', encoding='utf-8')
    result = write_stress_window(tmp_path)
    assert result['size'][0] == pytest.approx(.32)
    assert result['reconciliation_error'][0] == pytest.approx(0.)


def test_new_industry_restarts_covariance_without_zero_dilution():
    state = EWMARisk(2, minimum_history=60)
    state.begin_industry_regime({'SW2014:A'})
    first = dt.date(2019, 1, 1)
    for offset in range(400):
        state.update(first+dt.timedelta(days=offset), np.array([.01, 0.]), {'stock': .01})
    assert state.covariance() is not None
    assert state.begin_industry_regime({'SW2021:A'})
    assert state.covariance() is None
    assert state.specific['stock'][1] == 400
    fresh = EWMARisk(2, minimum_history=60)
    fresh.begin_industry_regime({'SW2021:A'})
    for offset in range(60):
        day = first+dt.timedelta(days=400+offset)
        returns = np.array([(-1)**offset*.01, (-1)**offset*.03])
        state.update(day, returns, {})
        fresh.update(day, returns, {})
        if offset < 59:
            assert state.covariance() is None
    np.testing.assert_allclose(state.covariance(), fresh.covariance(), atol=1e-16)
