import datetime as dt

import polars as pl
import pytest

from quant.data.forecast_text_corpus import normalize_forecasts


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
