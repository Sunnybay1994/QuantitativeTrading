import datetime as dt
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from quant.research.run_fixed_model_forecast import fixed_predict, model_features


DAY = dt.date(2026, 9, 10)


def fixture():
    universe = pl.DataFrame({'symbol': ['A', 'B', 'C', 'D'], 'trade_date': [DAY]*4,
        'eligible': [True]*4, 'total_market_value': [10.0, 15.0, 20.0, 30.0], 'industry_l1': ['bank']*4})
    values = {f: universe.select('symbol', 'trade_date').with_columns(pl.Series('value', y))
              for f, y in [('f1', [1.0, 2.0, 4.0, 8.0]), ('f2', [3.0, 5.0, 1.0, 2.0])]}
    return dict(universe=universe, values=values, directions={'f1': 1, 'f2': -1},
        settings={'variants': ['raw', 'size_industry_neutral'],
                  'preprocessing': {'mad_multiplier': 3.0, 'mad_normal_scale': 1.4826}},
        factors=['f1', 'f2'], variant='size_industry_neutral', as_of=DAY)


def test_neutralized_features_and_frozen_linear_weights():
    features, coverage = model_features(**fixture())
    assert features.height == 4 and all(row['eligible_finite_stocks'] == 4 for row in coverage)
    matrix = features.select('f1', 'f2').to_numpy()
    np.testing.assert_allclose(matrix.mean(axis=0), [0, 0], atol=1e-12)
    np.testing.assert_allclose(matrix.std(axis=0), [1, 1], atol=1e-12)
    fit = {'factors': ['f1', 'f2'], 'positive_mean_ic_weights': {'f1': 0.25, 'f2': 0.75}}
    result = fixed_predict(features=features, fit=fit, method='positive_mean_ic', source=Path('.'), minimum_symbols=3)
    np.testing.assert_allclose(result['prediction'], matrix @ np.array([0.25, 0.75]))


def test_missing_factor_produces_empty_predictions_not_liquidation():
    args = fixture()
    args['values']['f2'] = args['values']['f2'].with_columns(pl.lit(None, dtype=pl.Float64).alias('value'))
    features, coverage = model_features(**args)
    assert features.is_empty() and coverage[-1]['eligible_finite_stocks'] == 0
    result = fixed_predict(features=features, fit={'factors': ['f1', 'f2']}, method='lightgbm',
                           source=Path('not_opened_when_missing'), minimum_symbols=100)
    assert result.is_empty() and result.columns == ['symbol', 'trade_date', 'prediction']


def test_cross_date_and_duplicate_values_rejected():
    args = fixture()
    args['values']['f1'] = args['values']['f1'].with_columns(pl.lit(DAY+dt.timedelta(days=1)).alias('trade_date'))
    with pytest.raises(ValueError):
        model_features(**args)
    args = fixture()
    args['values']['f1'] = pl.concat([args['values']['f1']] * 2)
    with pytest.raises(pl.exceptions.ComputeError):
        model_features(**args)


def test_feature_column_order_follows_frozen_fit():
    features, _ = model_features(**fixture())
    fit = {'factors': ['f2', 'f1'], 'positive_mean_ic_weights': {'f1': 0.25, 'f2': 0.75}}
    result = fixed_predict(features=features, fit=fit, method='positive_mean_ic', source=Path('.'), minimum_symbols=3)
    expected = features['f1']*0.25 + features['f2']*0.75
    np.testing.assert_allclose(result['prediction'], expected)


@pytest.mark.parametrize('method', ['equal_z', 'positive_mean_ic'])
def test_missing_month_exclusion_matches_training_policy(method):
    args = fixture()
    args['values']['f2'] = args['values']['f2'].with_columns(pl.lit(None, dtype=pl.Float64).alias('value'))
    features, coverage = model_features(**args, missing_policy='neutral_zero_with_monthly_factor_exclusion')
    assert features.height == 4
    assert coverage[-1]['observed_stocks'] == 0 and coverage[-1]['active'] is False
    assert features['f2'].to_list() == [0.]*4
    fit = {'factors': ['f1', 'f2'], 'positive_mean_ic_weights': {'f1': .25, 'f2': .75},
           'missing_features': 'neutral_zero_with_monthly_factor_exclusion'}
    result = fixed_predict(features=features, fit=fit, method=method, source=Path('.'), minimum_symbols=3)
    np.testing.assert_allclose(result['prediction'], features['f1'])
    with pytest.raises(ValueError, match='flags'):
        fixed_predict(features=features.drop('__active_f2'), fit=fit, method=method,
                      source=Path('.'), minimum_symbols=3)
    with pytest.raises(ValueError, match='nonzero'):
        fixed_predict(features=features.with_columns(pl.lit(1.).alias('f2')), fit=fit,
                      method=method, source=Path('.'), minimum_symbols=3)
