import datetime as dt

import numpy as np
import polars as pl
import pytest

from quant.research.run_model_volatility_overlay import scale_targets, threshold_scale


def test_scale_reuses_trailing_sample_volatility_without_future_prices():
    dates = [dt.date(2020, 1, 1) + dt.timedelta(days=i) for i in range(80)]
    returns = np.array([.02, -.02] * 40)
    prices = pl.DataFrame({'date': dates, 'unit_nav': np.cumprod(1 + returns)})
    targets = pl.DataFrame({'as_of': [dates[65]] * 2, 'execution_date': [dates[66]] * 2,
        'strategy': ['model'] * 2, 'strategy_version': ['v1'] * 2,
        'symbol': ['600001.SH', '600002.SH'], 'weight': [.3, .6]})
    policy = {'lookback_observations': 60, 'annualized_target_volatility': .12,
              'annualization_sessions': 252}
    scaled, diagnostics = scale_targets(targets, prices, policy)
    expected = .12 / (np.std(returns[6:66], ddof=1) * np.sqrt(252))
    assert diagnostics['scale'][0] == pytest.approx(expected)
    assert scaled['weight'].to_list() == pytest.approx([.3 * expected, .6 * expected])
    future = prices.with_columns(pl.when(pl.col('date') > dates[65]).then(pl.col('unit_nav') * 100)
                                 .otherwise(pl.col('unit_nav')).alias('unit_nav'))
    again, _ = scale_targets(targets, future, policy)
    assert again.equals(scaled)
    assert scaled.drop('weight').equals(targets.drop('weight'))


def test_missing_history_zero_and_no_leverage():
    dates = [dt.date(2020, 1, i) for i in range(1, 6)]
    prices = pl.DataFrame({'date': dates, 'unit_nav': [1.] * 5})
    targets = pl.DataFrame({'as_of': [dates[-1]], 'strategy': ['model'],
        'strategy_version': ['v1'], 'symbol': ['600001.SH'], 'weight': [.8]})
    policy = {'lookback_observations': 60, 'annualized_target_volatility': .12,
              'annualization_sessions': 252}
    scaled, _ = scale_targets(targets, prices, policy)
    assert scaled['weight'][0] == 0
    scaled, _ = scale_targets(targets, prices, {**policy, 'lookback_observations': 2})
    assert scaled['weight'][0] == .8


@pytest.mark.parametrize('kind', ['moving_average', 'drawdown'])
def test_threshold_signals_ignore_future_and_restore_weight(kind):
    dates = [dt.date(2020, 1, day) for day in range(1, 7)]
    frame = pl.DataFrame({'date': dates, 'unit_nav': [1., 1., 1., .9, 1., 100.]})
    policy = {'kind': kind, 'lookback_observations': 3, 'reduced_weight': .5,
              'drawdown_threshold': .1}
    assert threshold_scale(frame, as_of=dates[3], policy=policy) == .5
    assert threshold_scale(frame, as_of=dates[4], policy=policy) == 1.
    assert threshold_scale(frame.head(4), as_of=dates[3], policy=policy) == .5
    assert threshold_scale(frame, as_of=dates[1], policy=policy) == 0.
    assert threshold_scale(frame.head(4), as_of=dates[4], policy=policy) == 0.
    with pytest.raises(ValueError, match='ordered'):
        threshold_scale(pl.concat([frame, frame.tail(1)]), as_of=dates[3], policy=policy)
