import datetime as dt
from pathlib import Path

import polars as pl
import pytest

from quant.reporting.rolling_signal_monitor import evaluate, run


def fixture():
    days = [dt.date(2024, month, 28) for month in range(1, 13)]
    exits = [dt.date(2024+(month == 12), month % 12+1, 1) for month in range(1, 13)]
    scores = pl.DataFrame({'trade_date': days, 'rank_ic': [.1, .2]*6,
        'forward_evidence': [True]*12, 'rehearsal': [False]*12})
    labels = pl.DataFrame({'trade_date': days, 'exit_date_rebalance': exits})
    return dict(scores=scores, labels=labels, known_through=dt.date(2025, 1, 1),
                windows=[12, 24, 36], minimum_months=12, lag=6, icir_warning=.3)


def test_realization_calendar_and_no_zero_imputation():
    args = fixture()
    r = evaluate(**args)
    assert r['windows'][0]['months'] == 12
    assert r['windows'][0]['status'] == 'within_monitor_threshold'
    args['labels'] = args['labels'].with_columns(pl.when(pl.col('trade_date').dt.month() == 12)
        .then(pl.lit(dt.date(2025, 2, 1))).otherwise(pl.col('exit_date_rebalance')).alias('exit_date_rebalance'))
    r = evaluate(**args)
    assert r['windows'][0]['months'] == 11 and r['windows'][0]['status'] == 'insufficient'
    assert r['excluded_or_unscored_records'] == 1


def test_rehearsal_cannot_count_as_forward_and_gaps_stay_missing():
    args = fixture()
    args['scores'] = args['scores'].with_columns(pl.lit(True).alias('rehearsal'))
    r = evaluate(**args)
    assert r['forward_months'] == 0 and r['historical_months'] == 12
    assert r['windows'][0]['mean_ic'] is None
    assert r['windows'][3]['months'] == 12


def test_low_icir_warning_requires_minimum_sample():
    args = fixture()
    args['scores'] = args['scores'].with_columns(-pl.col('rank_ic'))
    r = evaluate(**args)
    assert r['windows'][0]['warning'] is True
    args['scores'] = args['scores'].head(11)
    assert evaluate(**args)['windows'][0]['warning'] is False


def test_bad_labels_fail_closed():
    args = fixture()
    args['labels'] = pl.concat([args['labels'], args['labels'].head(1).with_columns(
        pl.col('exit_date_rebalance')+dt.timedelta(days=1))])
    with pytest.raises(ValueError, match='one later label'):
        evaluate(**args)


def test_no_accumulated_forward_is_insufficient(tmp_path):
    result = run(known_through=dt.date(2026, 9, 11), output=tmp_path/'monitor',
                 config=Path('configs/research/rolling_signal_monitor_v1.toml'))
    assert result['status'] == 'insufficient' and result['forward_scored_series_months'] == 0
    assert not result['requires_review']
    with pytest.raises(FileExistsError):
        run(known_through=dt.date(2026, 9, 11), output=tmp_path/'monitor')


def test_missing_forward_metadata_is_historical_and_saved_direction_is_fixed():
    args = fixture()
    args['scores'] = args['scores'].drop('forward_evidence', 'rehearsal')
    r = evaluate(**args)
    assert r['forward_months'] == 0 and r['historical_months'] == 12
    with pytest.raises(ValueError, match='registered monitoring'):
        evaluate(**args, direction=-1)
