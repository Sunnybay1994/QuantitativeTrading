import datetime as dt

import polars as pl
import pytest

from quant.reporting.factor_incremental_ic import incremental_ic


def panel():
    return pl.DataFrame({'symbol': [str(i) for i in range(8)], 'trade_date': [dt.date(2024, 1, 31)]*8,
        'a': [1., 2., 3., 4., 5., 6., 7., 8.], 'b': [3., 7., 1., 5., 2., 8., 4., 6.],
        'label_rebalance': [1., 2., 3., 4., 5., 6., 7., 8.], '__active_a': [True]*8, '__active_b': [True]*8})


def test_independent_signal_survives_identical_rank_controls():
    rows = {r['factor']: r for r in incremental_ic(panel(), factors=['a', 'b'], minimum_symbols=4)}
    assert rows['a']['raw_rank_ic'] == pytest.approx(1.)
    assert rows['a']['partial_rank_ic'] == pytest.approx(1.)
    assert rows['b']['reason'] == 'label_rank_explained_by_controls'
    assert rows['a']['common_stocks'] == rows['b']['common_stocks'] == 8


def test_copied_signal_is_unidentified_not_extra_information():
    frame = panel().with_columns(pl.col('a').alias('copy'), pl.lit(True).alias('__active_copy'))
    rows = {r['factor']: r for r in incremental_ic(frame, factors=['a', 'b', 'copy'], minimum_symbols=4)}
    assert rows['a']['reason'] == 'factor_rank_explained_by_controls'
    assert rows['copy']['partial_rank_ic'] is None
    assert rows['b']['reason'] == 'rank_deficient_controls'


def test_exclusions_and_missing_outcomes_keep_denominators():
    frame = panel().with_columns(pl.lit(0.).alias('b'), pl.lit(False).alias('__active_b'),
        pl.when(pl.col('a') > 5).then(None).otherwise(pl.col('label_rebalance')).alias('label_rebalance'))
    rows = {r['factor']: r for r in incremental_ic(frame, factors=['a', 'b'], minimum_symbols=4)}
    assert rows['a']['common_stocks'] == 5
    assert rows['a']['feature_stocks'] == 8
    assert rows['a']['partial_rank_ic'] == pytest.approx(1.)
    assert rows['b']['reason'] == 'monthly_excluded_or_no_valid_feature_pool'
    assert rows['a']['controls'] == '[]'
    assert incremental_ic(frame, factors=['a', 'b'], minimum_symbols=6)[0]['reason'] == 'insufficient_common_sample'


def test_constant_and_invalid_masks_are_not_silently_dropped():
    frame = panel().with_columns(pl.lit(0.).alias('b'))
    rows = {r['factor']: r for r in incremental_ic(frame, factors=['a', 'b'], minimum_symbols=4)}
    assert rows['a']['reason'] == 'rank_deficient_controls'
    assert rows['b']['reason'] == 'constant_factor'
    with pytest.raises(ValueError):
        incremental_ic(panel().with_columns((pl.col('a') > 3).alias('__active_a')), factors=['a', 'b'], minimum_symbols=4)
