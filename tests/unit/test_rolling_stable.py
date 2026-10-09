import datetime as dt

import numpy as np
import polars as pl

from quant.factors.expressions import evaluate_expressions, required_history


def panel(x, y=None):
    return pl.DataFrame({'symbol': ['A'] * len(x),
                         'trade_date': [dt.date(2020, 1, 1) + dt.timedelta(days=i) for i in range(len(x))],
                         'x': x, 'y': x if y is None else y})


def test_expired_extreme_and_prefix_invariance():
    x = [1e18, -1e18] + [0.0] * 12 + [1.0, 1.002, 0.999, 1.003, 1.001] * 8
    p = panel(x, [v * 0.002 + i % 3 for i, v in enumerate(x)])
    expressions = {k: f'{k}(x,5)' for k in
                   ['ts_mean', 'ts_sum', 'ts_std', 'ts_std0', 'ts_slope', 'ts_resi', 'ts_rsquare']}
    expressions.update(cov='ts_cov(x,y,5)', corr='ts_corr(x,y,5)',
                       nested='ts_rsquare(ts_cov(ts_std(x,5),y,5),5)')
    long = evaluate_expressions(p, expressions)
    short = evaluate_expressions(p.slice(5), expressions)
    for name, expression in expressions.items():
        warm = required_history(expression)
        np.testing.assert_array_equal(long[name].to_numpy()[5 + warm:], short[name].to_numpy()[warm:])
    assert long['ts_std'][10] == 0
    np.testing.assert_allclose(long['ts_std'][-1], np.std(x[-5:], ddof=1), rtol=1e-13)
    assert long['ts_std'][-1] > 0


def test_null_windows_and_independent_moments():
    x = [1., 2., None, 4., 7., 5., 9., 8.]
    y = [2., 1., 3., 1., 8., 4., 3., 9.]
    expressions = {'cov': 'ts_cov(x,y,4)', 'corr': 'ts_corr(x,y,4)',
                   'std': 'ts_std(x,4)', 'slope': 'ts_slope(x,4)', 'resi': 'ts_resi(x,4)'}
    result = evaluate_expressions(panel(x,y), expressions)
    for name in expressions:
        assert result[name][:6].null_count() == 6
    a, b = np.array(x[-4:]), np.array(y[-4:])
    slope, intercept = np.polyfit(np.arange(4), a, 1)
    np.testing.assert_allclose([result[k][-1] for k in expressions],
                              [np.cov(a,b)[0,1], np.corrcoef(a,b)[0,1], np.std(a,ddof=1),
                               slope, a[-1] - (intercept + 3 * slope)], atol=1e-14)


def test_symbol_boundaries_and_singleton_ddof():
    a = panel([100., 200., 300.])
    b = panel([1., 2., 3.]).with_columns(pl.lit('B').alias('symbol'))
    result = evaluate_expressions(pl.concat([a,b]), {'s':'ts_std(x,2)', 's1':'ts_std(x,1)', 'p1':'ts_std0(x,1)'})
    assert result['s'][3] is None
    assert result['s1'].null_count() == 6
    assert result['p1'].to_list() == [0.] * 6
