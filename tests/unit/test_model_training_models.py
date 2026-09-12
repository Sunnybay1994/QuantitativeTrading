import datetime as dt

import numpy as np
import polars as pl
import pytest

from quant.research.model_training_models import (
    buffered_model_targets, common_features, fit_predict, training_panel,
)


def test_common_pool_and_training_labels_exclude_missing_features_and_future(tmp_path):
    dates = [dt.date(2022, 10, 31), dt.date(2022, 11, 30)]
    keys = {'symbol': ['A', 'B', 'C']*2, 'trade_date': [dates[0]]*3+[dates[1]]*3}
    for name in ('a', 'b'):
        folder = tmp_path/'factors'/name
        folder.mkdir(parents=True)
        values = [1., 2., None, 1., 2., 3.] if name == 'b' else [1., 2., 3.]*2
        pl.DataFrame({**keys, 'neutral': values}).write_parquet(folder/'monthly_scores.parquet')
    inputs = tmp_path/'inputs'/'2022'
    inputs.mkdir(parents=True)
    labels = pl.DataFrame({**keys, 'exit_date_rebalance': [dt.date(2022, 12, 1)]*3+[dt.date(2023, 1, 3)]*3,
                          'label_rebalance': [.1, .2, .3, 999., 999., 999.]})
    labels.write_parquet(inputs/'monthly_labels.parquet')
    features = common_features(statistics=tmp_path, factors=['a', 'b'], variant='neutral',
                              start=dates[0], end=dates[1], minimum_symbols=2)
    assert features.height == 5
    known = training_panel(features=features, statistics=tmp_path, cutoff=dt.date(2022, 12, 30), minimum_symbols=2)
    assert known.height == 2
    assert known['label_rebalance'].to_list() == [.1, .2]


def test_models_share_rows_and_ic_weights_use_training_means():
    train_date, cutoff = dt.date(2022, 10, 31), dt.date(2022, 12, 30)
    training = pl.DataFrame({'symbol': [str(i) for i in range(30)], 'trade_date': [train_date]*30,
        'exit_date_rebalance': [dt.date(2022, 12, 1)]*30,
        'a': np.arange(30, dtype=float), 'b': -np.arange(30, dtype=float),
        'label_rebalance': np.arange(30, dtype=float)*.01})
    prediction = pl.DataFrame({'symbol': ['X', 'Y'], 'trade_date': [cutoff]*2,
                               'a': [1., 3.], 'b': [3., 1.]})
    settings = {'lightgbm': {'n_estimators': 5, 'num_leaves': 3, 'min_child_samples': 2,
                             'n_jobs': 1, 'random_state': 1, 'verbosity': -1}}
    result, metadata, _ = fit_predict(training=training, prediction=prediction, factors=['a', 'b'],
        mean_ic={'a': .3, 'b': .1}, cutoff=cutoff, settings=settings)
    assert result['symbol'].to_list() == ['X', 'Y']
    assert result['equal_z'].to_list() == [2., 2.]
    assert result['positive_mean_ic'].to_list() == pytest.approx([1.5, 2.5])
    assert result['lightgbm'].is_finite().all()
    assert metadata['last_known_exit'] == '2022-12-01'
    with pytest.raises(ValueError, match='information boundary'):
        fit_predict(training=training.with_columns(pl.lit(dt.date(2023, 1, 3)).alias('exit_date_rebalance')),
            prediction=prediction, factors=['a', 'b'], mean_ic={'a': .3, 'b': .1}, cutoff=cutoff, settings=settings)

    masked = prediction.with_columns(pl.lit(0.).alias('b'), pl.lit(True).alias('__active_a'),
                                     pl.lit(False).alias('__active_b'))
    scored, _, _ = fit_predict(training=training, prediction=masked, factors=['a', 'b'],
        mean_ic={'a': .3, 'b': .1}, cutoff=cutoff, settings=settings)
    assert scored['equal_z'].to_list() == [1., 3.]
    assert scored['positive_mean_ic'].to_list() == pytest.approx([1., 3.])
    with pytest.raises(ValueError, match='Invalid monthly factor exclusion'):
        fit_predict(training=training, prediction=masked.with_columns(pl.lit(False).alias('__active_a')),
            factors=['a', 'b'], mean_ic={'a': .3, 'b': .1}, cutoff=cutoff, settings=settings)


def test_neutral_imputation_uses_eligible_pool_and_monthly_exclusion(tmp_path):
    days = [dt.date(2023, 1, 31), dt.date(2023, 2, 28), dt.date(2023, 3, 31)]
    symbols = [str(i) for i in range(11)]
    keys = {'symbol': symbols*3, 'trade_date': [d for d in days for _ in symbols]}
    inputs = tmp_path/'inputs/2023'
    inputs.mkdir(parents=True)
    pl.DataFrame({**keys, 'eligible': ([True]*10+[False])*3}).write_parquet(inputs/'universe.parquet')
    for factor in ('a', 'b'):
        folder = tmp_path/'factors'/factor
        folder.mkdir(parents=True)
        values = ([1.]*22+[None]*11) if factor == 'a' else (
            [2.]*7+[None]*3+[999.]+[2.]*6+[None]*4+[999.]+[None]*11)
        pl.DataFrame({**keys, 'size_industry_neutral': values}).write_parquet(folder/'monthly_scores.parquet')
    kwargs = dict(statistics=tmp_path, factors=['a', 'b'], variant='size_industry_neutral',
        start=days[0], end=days[-1], minimum_symbols=10,
        missing_policy='neutral_zero_with_monthly_factor_exclusion')
    coverage = []
    result = common_features(**kwargs, coverage=coverage)
    b = [row for row in coverage if row['factor'] == 'b']
    assert [row['eligible_stocks'] for row in b] == [10, 10, 10]
    assert [row['observed_stocks'] for row in b] == [7, 6, 0]
    assert [row['active'] for row in b] == [True, False, False]
    first = result.filter(pl.col('trade_date') == days[0])
    second = result.filter(pl.col('trade_date') == days[1])
    assert first.height == second.height == 10
    assert first['__active_b'].all() and (first['b'] == 0).sum() == 3
    assert not second['__active_b'].any() and (second['b'] == 0).all()
    assert result.filter(pl.col('trade_date') == days[2]).is_empty()
    assert '10' not in result['symbol']
    # Excluding future months from the request cannot change January filling.
    assert first.equals(common_features(**{**kwargs, 'end': days[0]}))


def test_buffer_survives_refit_and_empty_pool_keeps_requesting_cash():
    dates = [dt.date(2022, 12, 30), dt.date(2023, 1, 31), dt.date(2023, 2, 28), dt.date(2023, 3, 31)]
    scores = pl.DataFrame({'symbol': ['A', 'B', 'C']*2, 'trade_date': [dates[0]]*3+[dates[1]]*3,
                           'equal_z': [3., 2., 1., 2., 1., 3.]})
    sessions = (dates[0], dt.date(2023, 1, 3), dates[1], dt.date(2023, 2, 1), dates[2],
                dt.date(2023, 3, 1), dates[3], dt.date(2023, 4, 3))
    targets = buffered_model_targets(scores, method='equal_z', sessions=sessions,
        start=dt.date(2023, 1, 1), end=dt.date(2023, 4, 3), top_k=2, minimum_symbols=3, retention_multiplier=1.5)
    feb = targets.filter(pl.col('execution_date') == dt.date(2023, 2, 1))
    assert feb['symbol'].to_list() == ['A', 'B']  # Retention band preserves the old pair.
    assert feb['weight'].sum() == 1.
    assert targets.filter(pl.col('as_of') >= pl.col('execution_date')).is_empty()
    for date in (dt.date(2023, 3, 1), dt.date(2023, 4, 3)):
        cash = targets.filter(pl.col('execution_date') == date)
        assert cash.height and cash['weight'].sum() == 0.
