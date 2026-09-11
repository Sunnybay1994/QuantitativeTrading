import datetime as dt

import polars as pl
import pytest

from quant.research.model_training_costs import prefix_cost_report


def fixture():
    dates = [dt.date(2020, 1, day) for day in (2, 3, 6)]
    nav = pl.DataFrame({'date': dates, 'equity': [100., 110., 200.], 'unit_nav': [1., 1.1, 2.],
                       'market_value': [50., 55., 100.], 'cumulative_fees': [0., 1., 10.]})
    trades = pl.DataFrame({'date': dates, 'notional': [100., 50., 1000.]})
    baseline = pl.DataFrame({'date': dates, 'unit_nav': [1., 1.05, 10.]})
    return dates, nav, trades, baseline


def test_future_nav_trades_and_benchmark_do_not_affect_prefix():
    dates, nav, trades, baseline = fixture()
    kwargs = dict(factor='a', cutoff=dates[1], initial_cash=100.)
    original = prefix_cost_report(histories={('raw', 1.): (nav, trades)},
        benchmarks={('all_market_equal_weight', 1.): baseline}, **kwargs)
    future = pl.col('date') > dates[1]
    nav = nav.with_columns([pl.when(future).then(999.).otherwise(pl.col(name)).alias(name)
                           for name in ('equity', 'unit_nav', 'market_value', 'cumulative_fees')])
    trades = trades.with_columns(pl.when(future).then(99999.).otherwise(pl.col('notional')).alias('notional'))
    baseline = baseline.with_columns(pl.when(future).then(.01).otherwise(pl.col('unit_nav')).alias('unit_nav'))
    changed = prefix_cost_report(histories={('raw', 1.): (nav, trades)},
        benchmarks={('all_market_equal_weight', 1.): baseline}, **kwargs)
    assert original == changed
    row = original['rows'][0]
    assert row['last_date'] == str(dates[1])
    assert row['ending_equity'] == 110.
    assert row['gross_traded_notional'] == 150.
    assert row['cumulative_fees'] == 1.
    assert original['benchmark_comparisons'][0]['net_cagr_excess'] > 0


def test_pre_inception_has_no_cost_evidence_and_missing_refit_is_rejected():
    dates, nav, trades, baseline = fixture()
    histories = {('raw', 1.): (nav, trades)}
    kwargs = dict(factor='a', initial_cash=100.)
    assert prefix_cost_report(histories=histories, benchmarks={}, cutoff=dt.date(2019, 12, 31),
                              **kwargs)['rows'] == []
    with pytest.raises(ValueError, match='Cost history is missing'):
        prefix_cost_report(histories=histories, benchmarks={}, cutoff=dt.date(2020, 1, 7), **kwargs)
    with pytest.raises(ValueError, match='Benchmark history is missing'):
        prefix_cost_report(histories=histories, benchmarks={('all_market_equal_weight', 1.): baseline.head(1)},
                           cutoff=dates[1], **kwargs)


def test_benchmarks_use_matching_cost_multiplier_and_common_window():
    dates, nav, trades, baseline = fixture()
    baseline = baseline.with_columns(pl.lit(1.).alias('unit_nav'))
    report = prefix_cost_report(factor='a', histories={('raw', 1.): (nav, trades)},
        benchmarks={('all_market_equal_weight', 2.): baseline,
                    ('510300_total_return_reference', None): baseline}, cutoff=dates[-1], initial_cash=100.)
    assert len(report['benchmark_comparisons']) == 1
    assert report['benchmark_comparisons'][0]['benchmark'] == '510300_total_return_reference'
