import datetime as dt

import polars as pl
import pytest

from quant.data.model_forecast_labels import monthly_schedule
from quant.research.score_model_forecasts import score_record

DAY = dt.date(2026, 1, 30)
ENTRY = dt.date(2026, 2, 2)
EXIT = dt.date(2026, 3, 2)
SESSIONS = (DAY, ENTRY, dt.date(2026, 2, 27), EXIT, dt.date(2026, 3, 31), dt.date(2026, 4, 1))


def inputs():
    predictions = pl.DataFrame({'symbol': ['A', 'B', 'C', 'D'], 'trade_date': [DAY]*4,
                                'prediction': [1., 2., 3., 4.]})
    labels = predictions.select('symbol', 'trade_date').with_columns(
        pl.lit(ENTRY).alias('execution_date_rebalance'), pl.lit(EXIT).alias('exit_date_rebalance'),
        pl.Series('label_rebalance', [.1, .4, .2, .3]))
    return dict(predictions=predictions, labels=labels, sessions=SESSIONS, known_through=EXIT,
        record={'as_of': str(DAY), 'rehearsal': False, 'recorded_at': '2026-01-30T17:00:00+08:00'},
        forward_start=DAY, minimum_symbols=3, minimum_paired_coverage=.95)


def test_realized_rank_ic_and_pending_future_even_when_labels_present():
    args = inputs()
    result = score_record(**args)
    assert result['rank_ic'] == pytest.approx(.4)
    assert result['forward_evidence'] is True
    args['known_through'] = dt.date(2026, 2, 27)
    result = score_record(**args)
    assert result['status'] == 'awaiting_realized_return' and result['rank_ic'] is None


@pytest.mark.parametrize('stamp', [None, '2026-02-02T09:30:00+08:00', '2026-01-30T14:59:00+08:00', '2026-01-30T17:00:00'])
def test_late_missing_early_or_naive_timestamp_never_forward(stamp):
    args = inputs()
    args['record']['recorded_at'] = stamp
    assert score_record(**args)['forward_evidence'] is False


def test_rehearsal_and_prestart_remain_retrospective():
    args = inputs()
    args['record']['rehearsal'] = True
    assert score_record(**args)['forward_evidence'] is False
    args['record']['rehearsal'] = False
    args['forward_start'] = ENTRY
    assert score_record(**args)['forward_evidence'] is False


def test_missing_prices_keep_original_cohort_denominator():
    args = inputs()
    args['labels'] = args['labels'].head(3)
    result = score_record(**args)
    assert result['paired_coverage'] == .75
    assert result['rank_ic'] is None and result['status'] == 'insufficient_pairs'


def test_duplicate_forecasts_or_wrong_exit_fail():
    args = inputs()
    args['predictions'] = pl.concat([args['predictions']]*2)
    with pytest.raises(ValueError, match='unique'):
        score_record(**args)
    args = inputs()
    args['labels'] = args['labels'].with_columns(pl.lit(ENTRY).alias('exit_date_rebalance'))
    with pytest.raises(ValueError, match='exact'):
        score_record(**args)


def test_calendar_does_not_skip_missing_month_or_score_non_monthend():
    assert monthly_schedule(SESSIONS, DAY) == (ENTRY, EXIT)
    assert monthly_schedule(SESSIONS, ENTRY) is None
    assert monthly_schedule((DAY, dt.date(2026, 3, 31), dt.date(2026, 4, 1)), DAY) is None
