import datetime as dt

import polars as pl
import pytest

from quant.research.factor_battery_redundancy import (
    correlation_maxima, monthly_rank_correlation, summarize_correlation,
)


def test_reranks_common_stocks_and_preserves_missing_months():
    first, second = dt.date(2020, 1, 31), dt.date(2020, 2, 28)
    left = pl.DataFrame({'trade_date': [first]*4+[second]*4,
                        'symbol': ['a', 'b', 'c', 'd']*2, 'raw': [1., 2., 3., 4.]*2})
    # Removing b changes rank distances: reranking a,c,d gives exactly -1.
    right = pl.DataFrame({'trade_date': [first]*3+[second]*2,
                         'symbol': ['a', 'c', 'd', 'a', 'c'], 'raw': [3., 2., 1., 2., 1.]})
    monthly = monthly_rank_correlation(left, right, variant='raw', minimum_symbols=3)
    assert monthly['common_symbols'].to_list() == [3, 2]
    assert monthly['rank_correlation'].to_list() == [-1., None]
    summary = summarize_correlation(monthly, minimum_months=2)
    assert summary['comparison_qualified'] is False
    assert summary['mean_absolute_rank_correlation'] == 1.


def test_sign_reversal_does_not_cancel_redundancy_and_constant_month_is_missing():
    dates = [dt.date(2020, m, 28) for m in (1, 2, 3)]
    left = pl.DataFrame({'trade_date': [d for d in dates for _ in range(3)],
                        'symbol': ['a', 'b', 'c']*3, 'raw': [1., 2., 3.]*3})
    right = left.with_columns(pl.Series('raw', [1., 2., 3., 3., 2., 1., 1., 1., 1.]))
    monthly = monthly_rank_correlation(left, right, variant='raw', minimum_symbols=3)
    summary = summarize_correlation(monthly, minimum_months=2)
    assert summary['mean_rank_correlation'] == 0.
    assert summary['mean_absolute_rank_correlation'] == 1.
    assert summary['months'] == 2
    assert summary['comparison_qualified'] is True
    with pytest.raises(ValueError, match='Duplicate'):
        monthly_rank_correlation(pl.concat([left, left.head(1)]), right, variant='raw', minimum_symbols=3)


def test_maxima_use_primary_order_ties_and_qualified_comparisons():
    settings = {'variants': ['raw'], 'primary_variant': 'raw',
                'admission': {'maximum_absolute_rank_correlation_with_better': .7}}
    statistics = pl.DataFrame({'factor': ['a', 'b', 'c'], 'variant': ['raw']*3, 'icir': [.8, .8, .3]})
    pairs = pl.DataFrame({'left': ['a', 'a', 'b'], 'right': ['b', 'c', 'c'], 'variant': ['raw']*3,
                         'comparison_qualified': [True, False, True], 'months': [100, 2, 110],
                         'mean_absolute_rank_correlation': [.7, 1., .2]})
    result = correlation_maxima(pairs, statistics, settings=settings).sort('factor')
    assert result['redundant_with_higher'].to_list() == [False, True, False]
    assert result['higher_most_correlated_factor'].to_list() == [None, 'a', 'b']
    assert result['all_most_correlated_factor'].to_list() == ['b', 'a', 'b']
    assert result['qualified_peer_count'].to_list() == [1, 2, 1]
