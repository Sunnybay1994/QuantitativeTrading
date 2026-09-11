import datetime as dt

import polars as pl
import pytest

from quant.data.forecast_text_corpus import (
    monthly_coverage, normalize_forecasts, select_historical_scope,
)


def sample():
    return pl.DataFrame({
        'ts_code': ['600519.SH', '600519.SH'],
        'ann_date': ['20241230', '20250113'],
        'first_ann_date': ['20241230', '20241230'],
        'end_date': ['20241231', '20241231'],
        'change_reason': [' 增长 ', '修订'],
    })


def test_revision_uses_own_date_and_allows_forecast_before_period_end():
    result = normalize_forecasts(sample())
    assert result['publication_date'].to_list() == [dt.date(2024, 12, 30), dt.date(2025, 1, 13)]
    assert result['reason_text'].to_list() == ['增长', '修订']
    assert result['availability'].to_list() == ['after_close', 'after_close']


def test_duplicates_collapse_but_conflicting_same_day_releases_are_flagged():
    first = sample().head(1)
    conflict = first.with_columns(pl.lit('不同原因').alias('change_reason'))
    result = normalize_forecasts(pl.concat([first, first, conflict]))
    assert result.height == 2
    assert result['same_day_conflict'].to_list() == [True, True]


def test_blank_text_remains_missing():
    result = normalize_forecasts(sample().with_columns(pl.lit('  ').alias('change_reason')))
    assert result['reason_text'].null_count() == 2


def test_missing_date_rejected():
    with pytest.raises(ValueError, match='Invalid forecast'):
        normalize_forecasts(sample().with_columns(pl.lit(None, dtype=pl.String).alias('ann_date')))


def test_historical_scope_keeps_delisted_and_excludes_late_listings(tmp_path):
    source = tmp_path/'stocks.parquet'
    pl.DataFrame({
        'ts_code': ['600001.SH', '600002.SH', '600003.SH', '600004.SH'],
        'list_date': ['20000101', '20000101', '20180101', '20000101'],
        'delist_date': [None, '20200101', None, '20090101'],
    }).write_parquet(source)
    selected = select_historical_scope([source], tmp_path/'scope.json', count=2)
    assert selected['symbols'] == ['600001.SH', '600002.SH']


def test_coverage_never_uses_future_text_or_keeps_superseded_text():
    source = sample().with_columns(pl.Series('change_reason', ['old reason', None]))
    result = monthly_coverage(normalize_forecasts(source),
                              start=dt.date(2024, 12, 1), end=dt.date(2025, 1, 31))
    assert result.filter(pl.col('as_of') == dt.date(2024, 12, 31))['reason_symbols'].to_list() == [1]*3
    assert result.filter(pl.col('as_of') == dt.date(2025, 1, 31))['reason_symbols'].to_list() == [0]*3


def test_coverage_expires_old_text():
    result = monthly_coverage(normalize_forecasts(sample().head(1)),
                              start=dt.date(2025, 5, 1), end=dt.date(2025, 5, 31))
    assert result['reason_symbols'].to_list() == [0]*3
