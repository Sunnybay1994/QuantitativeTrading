import datetime as dt

import polars as pl
import pytest

from quant.research.model_training_models import common_features, training_panel
from quant.research.run_calendar_input_model import replacement_factors


def test_replacements_preserve_order_and_unchanged_factors():
    assert replacement_factors(['a', 'old', 'b'], {'old': 'new'}) == ['a', 'new', 'b']
    with pytest.raises(ValueError):
        replacement_factors(['a', 'old'], {'old': 'a'})
    with pytest.raises(ValueError):
        replacement_factors(['a'], {'missing': 'new'})


def test_partitioned_calendar_scores_join_and_training_excludes_future_labels(tmp_path):
    dates = [dt.date(2023, 12, 29), dt.date(2024, 1, 31)]
    frame = pl.DataFrame({'symbol': ['A', 'A'], 'trade_date': dates,
                          'size_industry_neutral': [0.1, 0.2]})
    original, first, second = (tmp_path/name for name in ('original', 'training', 'validation'))
    for root, name, part in [(original, 'old', frame), (first, 'new', frame.head(1)),
                              (second, 'new', frame.tail(1))]:
        folder = root/'factors'/name
        folder.mkdir(parents=True)
        part.write_parquet(folder/'monthly_scores.parquet')
    features = common_features(statistics=original, factors=['old', 'new'], variant='size_industry_neutral',
        start=dates[0], end=dates[-1], minimum_symbols=1, statistics_sources={'new': [first, second]})
    assert features.height == 2 and features['old'].equals(features['new'])
    folder = original/'inputs'/'2024'
    folder.mkdir(parents=True)
    labels = frame.select('symbol', 'trade_date').with_columns(
        pl.Series('exit_date_rebalance', [dt.date(2024, 1, 2), dt.date(2024, 2, 1)]),
        pl.Series('label_rebalance', [0.03, 999.0]))
    labels.write_parquet(folder/'monthly_labels.parquet')
    train = training_panel(features=features, statistics=original, cutoff=dates[-1], minimum_symbols=1)
    assert train.height == 1 and train['label_rebalance'][0] == 0.03
    with pytest.raises(ValueError, match='Duplicate'):
        common_features(statistics=original, factors=['old', 'new'], variant='size_industry_neutral',
            start=dates[0], end=dates[-1], minimum_symbols=1, statistics_sources={'new': [first, first, second]})
