import datetime as dt
import importlib.util
import os
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from scipy.stats import rankdata, spearmanr


from quant.research.nightly_gp import maximum_correlation as original
from quant.research import n4_correlation as implementation
optimized = implementation.maximum_correlation
rank_shared = implementation.common_support_score_ranks


@pytest.mark.parametrize('seed', range(8))
def test_rank_matrix_exact_on_unique_and_repeated_missingness_ties_and_layout(seed):
    rng = np.random.default_rng(seed)
    y = rng.integers(-9, 10, size=203).astype(float)
    mask = rng.uniform(size=(len(y), 31)) > .3
    mask[:, 5:13] = mask[:, 0, None]
    mask[:, 14] = False
    mask[:, 15] = True
    expected = rankdata(np.where(mask, y[:, None], np.nan), axis=0, nan_policy='omit')
    actual = rank_shared(y, mask)
    np.testing.assert_array_equal(actual, expected)
    assert actual.flags.f_contiguous == expected.flags.f_contiguous


@pytest.mark.parametrize('seed', range(8))
@pytest.mark.parametrize('minimum', [3, 30, 100])
def test_exact_maximum_parity_on_mixed_support_constant_nonfinite_and_reordered_rows(seed, minimum):
    rng = np.random.default_rng(seed)
    n = 603
    y = rng.integers(-12, 13, size=n).astype(float)
    y[::31] = np.nan
    y[::113] = np.inf
    values = rng.integers(-15, 16, size=(n, 16)).astype(float)
    values[rng.uniform(size=values.shape) < .2] = np.nan
    values[:, 4:8] = np.where(np.isfinite(values[:, 0, None]), values[:, 4:8], np.nan)
    values[:, 10] = 2.0
    values[:, 11] = np.nan
    values[::11, 12] = -np.inf
    names = [f'x{i}' for i in range(values.shape[1])]
    frame = pl.DataFrame({'trade_date': [dt.date(2020, i // 201 + 1, 28) for i in range(n)],
        'score': y, **{name: values[:, i] for i, name in enumerate(names)}})
    frame = frame.sample(fraction=1, shuffle=True, seed=seed)
    assert optimized(frame, 'score', names, minimum) == original(frame, 'score', names, minimum)


def test_independent_pairwise_spearman_and_absolute_before_monthly_aggregation():
    rows = []
    for month in (1, 2, 3):
        for i in range(12):
            rows.append({'trade_date': dt.date(2020, month, 28), 'score': float(i // 2),
                'a': float((i * 5) % 12) if i % 4 else None,
                'b': float(i) * (-1 if month == 2 else 1),
                'future_response_not_used': float(i * month)})
    frame = pl.DataFrame(rows)
    expected = []
    for name in ['a', 'b']:
        correlations = []
        for part in frame.partition_by('trade_date'):
            part = part.drop_nulls(['score', name])
            correlations.append(abs(spearmanr(part['score'].to_numpy(), part[name].to_numpy()).statistic))
        expected.append(np.mean(correlations))
    assert optimized(frame, 'score', ['a', 'b'], 5) == pytest.approx(max(expected), abs=1e-14)
    assert optimized(frame, 'score', ['a', 'b'], 5) == original(frame, 'score', ['a', 'b'], 5)
    changed = frame.with_columns(pl.lit(99999).alias('future_response_not_used'))
    assert optimized(changed, 'score', ['a', 'b'], 5) == optimized(frame, 'score', ['a', 'b'], 5)


def test_unknown_and_insufficient_remain_conservative_one():
    frame = pl.DataFrame({'trade_date': [dt.date(2020, 1, 31)] * 8, 'score': [1.] * 8, 'c': range(8)})
    for subset in [frame, frame.head(0), frame.head(2)]:
        assert optimized(subset, 'score', ['c'], 5) == original(subset, 'score', ['c'], 5) == 1.


def test_no_cross_call_cache_or_support_reuse():
    a = pl.DataFrame({'trade_date': [dt.date(2020, 1, 31)] * 8,
        'score': [1., 2., 2., 4., 5., 6., 7., 8.], 'c': [1., None, 3., 4., None, 6., 8., 7.]})
    b = a.with_columns(pl.Series('c', [8., 7., None, 4., 6., 1., None, 2.]))
    for frame in [a, b, a]:
        assert optimized(frame, 'score', ['c'], 3) == original(frame, 'score', ['c'], 3)
