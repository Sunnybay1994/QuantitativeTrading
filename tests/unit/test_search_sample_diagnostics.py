import datetime as dt

import polars as pl

from quant.research.search_sample_diagnostics import compare_sample


def test_saved_keys_labels_and_time_windows_remain_separate():
    day = dt.date(2020, 1, 31)
    sample = pl.DataFrame({'symbol': [str(i) for i in range(100)], 'trade_date': [day]*100,
                           'label': list(range(100))})
    scores = sample.select('symbol', 'trade_date', pl.col('label').cast(pl.Float64).alias('raw'))
    labels = sample.select('symbol', 'trade_date', (-pl.col('label')).alias('label_rebalance'))
    monthly = pl.DataFrame({'trade_date': [dt.date(2019, 12, 31), day, dt.date(2020, 2, 28)],
                            'variant': ['raw']*3, 'rank_ic': [-.1, .2, -.3], 'paired_count': [200]*3})
    result = compare_sample(sample, scores, labels, monthly)
    comparisons = result['search_keys_with_battery_scores']
    assert comparisons['saved_search_labels']['mean_ic'] == 1
    assert comparisons['battery_labels_same_coverage']['mean_ic'] == -1
    assert result['label_difference_over_1e_12_rows'] == 99
    assert result['all_battery_stocks_by_window']['search_dates']['mean_ic'] == .2
    assert result['all_battery_stocks_by_window']['after_search']['mean_ic'] == -.3
    assert result['all_battery_stocks_by_window']['other_dates_inside_span']['months'] == 0


def test_missing_battery_scores_do_not_shrink_search_key_denominator():
    day = dt.date(2020, 1, 31)
    sample = pl.DataFrame({'symbol': [str(i) for i in range(100)], 'trade_date': [day]*100,
                           'label': list(range(100))})
    scores = sample.head(99).select('symbol', 'trade_date', pl.col('label').cast(pl.Float64).alias('raw'))
    labels = sample.rename({'label': 'label_rebalance'})
    monthly = pl.DataFrame({'trade_date': [day], 'variant': ['raw'], 'rank_ic': [.1], 'paired_count': [200]})
    result = compare_sample(sample, scores, labels, monthly)
    assert result['search_key_rows'] == 100 and result['battery_score_available_rows'] == 99
    assert result['search_keys_with_battery_scores']['saved_search_labels']['months'] == 0
