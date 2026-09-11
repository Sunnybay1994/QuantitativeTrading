import datetime as dt
import math

import numpy as np
import polars as pl
import pytest

from quant.reporting.stratified_signals import assign_strata, conditional_returns, market_states, signal_diagnostics


def test_annual_strata_do_not_use_future_controls_and_preserve_unknown():
    dates = [dt.date(2022, month, 28) for month in range(1, 13)] + [dt.date(2023, 1, 31)]
    controls = pl.DataFrame([{'symbol': symbol, 'trade_date': day, 'eligible': True,
        'amount20': amount, 'total_market_value': amount*10 if amount else None, 'industry_l1': 'bank'}
        for day in dates for symbol, amount in [('A', 10.), ('B', 20.), ('C', 30.), ('D', None)]])
    args = {'quantiles': [1/3, 2/3], 'minimum_months': 12}
    panel, thresholds = assign_strata(controls, **args)
    latest = panel.filter(pl.col('trade_date') == dates[-1]).sort('symbol')
    assert latest['liquidity'].to_list() == ['low', 'middle', 'high', 'unknown']
    assert thresholds.filter(pl.col('diagnostic_year') == 2023)['last_training_date'][0] == dates[-2]
    future = controls.tail(4).with_columns(pl.lit(dt.date(2024, 1, 31)).alias('trade_date'), pl.lit(1e12).alias('amount20'))
    extended, _ = assign_strata(pl.concat([controls, future]), **args)
    assert extended.filter(pl.col('trade_date') == dates[-1]).sort('symbol').equals(latest)


def test_strata_reject_bad_grid_and_duplicate_controls():
    with pytest.raises(ValueError):
        assign_strata(pl.DataFrame(), quantiles=[.5], minimum_months=12)


def test_market_states_use_previous_close_and_prior_year_threshold():
    dates = [dt.date(2022, 1, 1)+dt.timedelta(days=n) for n in range(600)]
    values = np.exp(np.arange(600)*.001 + np.sin(np.arange(600))*.01)
    prices = pl.DataFrame({'date': dates, 'unit_nav': values})
    expected = market_states(prices)
    assert expected.head(450).equals(market_states(prices.head(450)))
    changed = prices.with_columns(pl.when(pl.col('date') == dates[450]).then(.01).otherwise(pl.col('unit_nav')).alias('unit_nav'))
    actual = market_states(changed)
    assert actual.filter(pl.col('date') == dates[450]).equals(expected.filter(pl.col('date') == dates[450]))
    assert actual['prior_vol20'][451] != expected['prior_vol20'][451]


def signal_inputs(day=dt.date(2023, 6, 30)):
    symbols = [str(n) for n in range(10)]
    scores = pl.DataFrame({'symbol': symbols, 'trade_date': [day]*10, 'score': [float(n) for n in range(10)]})
    controls = scores.select('symbol', 'trade_date').with_columns(
        pl.lit('low').alias('liquidity'), pl.lit('high').alias('size'), pl.lit('bank').alias('industry'), pl.lit('low').alias('market_liquidity'))
    labels = scores.select('symbol', 'trade_date').with_columns(pl.lit(dt.date(2023, 8, 1)).alias('exit_date_rebalance'),
        pl.Series('label_rebalance', [-n*.01 for n in range(10)]))
    states = pl.DataFrame({'signal_date': [day], 'trend': ['bear'], 'volatility': ['high']})
    return dict(scores=scores, controls=controls, labels=labels, states=states, name='test', end=dt.date(2025, 12, 31),
        settings={'training_end': dt.date(2023, 12, 29), 'minimum_symbols': 3, 'minimum_paired_coverage': .95, 'monthly_newey_west_lag': 6})


def test_signal_ic_top_decile_and_missing_label_denominator():
    args = signal_inputs()
    detail, _ = signal_diagnostics(**args)
    all_row = detail.filter(pl.col('dimension') == 'all').row(0, named=True)
    assert all_row['rank_ic'] == pytest.approx(-1)
    assert all_row['top_gross_excess'] == pytest.approx(-.045)
    args['labels'] = args['labels'].head(5)
    detail, _ = signal_diagnostics(**args)
    all_row = detail.filter(pl.col('dimension') == 'all').row(0, named=True)
    assert all_row['signal_count'] == 10 and all_row['paired_coverage'] == .5
    assert all_row['rank_ic'] is None and all_row['top_gross_excess'] is None


def test_development_labels_remain_cut_off_even_when_later_returns_known():
    args = signal_inputs(dt.date(2023, 11, 30))
    args['labels'] = args['labels'].with_columns(pl.lit(dt.date(2024, 1, 2)).alias('exit_date_rebalance'))
    detail, summary = signal_diagnostics(**args)
    assert detail['rank_ic'].null_count() == detail.height
    assert summary['months'].sum() == 0


def test_monthly_summary_restores_order_after_joins():
    args = signal_inputs()
    earlier = signal_inputs(dt.date(2023, 5, 31))
    for key in ('scores', 'controls', 'labels', 'states'):
        args[key] = pl.concat([args[key], earlier[key]])
    detail, summary = signal_diagnostics(**args)
    assert detail.filter(pl.col('dimension') == 'all')['trade_date'].is_sorted()
    assert summary.filter(pl.col('dimension') == 'all')['months'][0] == 2


def test_conditional_log_contributions_reconcile_actual_path():
    daily = pl.DataFrame({'trend': ['bull', 'bear', 'bull'], 'daily_return': [.1, -.1, .05],
        'benchmark_daily_return': [.02, -.03, .01],
        'one_way_turnover': [.2, .3, .1], 'fee': [1., 2., 3.], 'slippage_cost': [4., 5., 6.]})
    rows = conditional_returns(daily, 'trend')
    assert sum(r['log_return_contribution'] for r in rows) == pytest.approx(math.log(1.1*.9*1.05))
    assert sum(r['one_way_turnover_sum'] for r in rows) == pytest.approx(.6)
    assert sum(r['log_relative_return_contribution'] for r in rows) == pytest.approx(math.log(1.1*.9*1.05/(1.02*.97*1.01)))
