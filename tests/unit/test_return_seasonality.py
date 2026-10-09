import datetime as dt

import numpy as np
import polars as pl
from polars.testing import assert_frame_equal
import pytest

from quant.factors.return_seasonality import (SEASONALITY_NAMES, CONTROL_NAMES,
    calendar_month_returns, compute_return_seasonality)


def fixture():
    day, end = dt.date(2010, 1, 1), dt.date(2026, 2, 3)
    sessions = []
    while day <= end:
        if day.weekday() < 5:
            sessions.append(day)
        day += dt.timedelta(days=1)
    ends = [a for a, b in zip(sessions, sessions[1:]) if a.month != b.month]
    rng = np.random.default_rng(600)
    values = rng.normal(0, .04, (4, len(ends)))
    monthly = pl.concat([pl.DataFrame({'symbol': str(i), 'trade_date': ends, 'monthly_return': values[i]})
                         for i in range(4)])
    signals = tuple(d for d in ends if (d.year, d.month) in [(2020, 12), (2021, 1), (2021, 2)])
    return monthly, tuple(sessions), signals


def run(monthly, sessions, signals):
    return compute_return_seasonality(monthly, sessions=sessions, signal_dates=signals)


def test_paper_lags_next_target_month_and_raw_nann_direction():
    monthly, sessions, signals = fixture()
    result = run(monthly, sessions, signals)
    for row in result.to_dicts():
        target = row['target_month']
        assert target.month == row['trade_date'].month % 12 + 1
        assert row['effective_date'] > row['trade_date']
        assert row['status'] == 'ok'
        t = target.year * 12 + target.month
        data = monthly.filter(pl.col('symbol') == row['symbol']).to_dicts()
        chosen = [(t - (r['trade_date'].year * 12 + r['trade_date'].month), r['monthly_return']) for r in data]
        chosen = [(k, v) for k, v in chosen if 13 <= k <= 60]
        ann = [v for k, v in chosen if k % 12 == 0]
        other = [v for k, v in chosen if k % 12 != 0]
        assert len(ann) == 4 and len(other) == 44
        expected = [np.mean(ann), np.mean(other), np.mean(ann) - np.mean(other)]
        assert [row[n] for n in SEASONALITY_NAMES] == pytest.approx(expected, abs=1e-14)
        assert row[CONTROL_NAMES[0]] == pytest.approx(np.mean([v for _, v in chosen]))
        assert row[CONTROL_NAMES[1]] == pytest.approx(np.prod([1+v for _, v in chosen])-1)
        assert row['window_start_month'] == dt.date(target.year-5, target.month, 1)


@pytest.mark.parametrize('bad', [None, float('nan'), float('inf'), -1.01])
def test_one_missing_annual_month_invalidates_whole_shared_family(bad):
    monthly, sessions, signals = fixture()
    date = monthly.filter((pl.col('trade_date').dt.year() == 2016) & (pl.col('trade_date').dt.month() == 1))['trade_date'][0]
    monthly = monthly.with_columns(pl.when((pl.col('symbol') == '0') & (pl.col('trade_date') == date))
        .then(pl.lit(bad, dtype=pl.Float64)).otherwise(pl.col('monthly_return')).alias('monthly_return'))
    row = run(monthly, sessions, signals).filter((pl.col('symbol') == '0') & (pl.col('trade_date') == signals[0])).row(0, named=True)
    assert row['valid_same_months'] == 3 and row['valid_other_months'] == 44
    assert row['status'] == 'incomplete_months'
    assert all(row[n] is None for n in (*SEASONALITY_NAMES, *CONTROL_NAMES))


def test_absent_month_is_not_compressed_and_new_null_clears_old_signal():
    monthly, sessions, signals = fixture()
    monthly = monthly.filter(~((pl.col('trade_date').dt.year() == 2020) & (pl.col('trade_date').dt.month() == 1)))
    result = run(monthly, sessions, signals).filter(pl.col('symbol') == '0')
    assert result['status'].to_list() == ['ok', 'incomplete_months', 'incomplete_months']
    assert result[SEASONALITY_NAMES[0]][0] is not None
    assert result[SEASONALITY_NAMES[0]][1] is None


def test_future_and_skipped_year_perturbations_and_prefix_leave_signals_unchanged():
    monthly, sessions, signals = fixture()
    baseline = run(monthly, sessions, signals[:1])
    changed = monthly.with_columns(pl.when(pl.col('trade_date') >= dt.date(2020, 1, 1))
        .then(pl.col('monthly_return') * 9 + .1).otherwise(pl.col('monthly_return')).alias('monthly_return'))
    assert_frame_equal(run(changed, sessions, signals[:1]), baseline, check_exact=True)
    assert_frame_equal(run(monthly.filter(pl.col('trade_date') <= signals[0]), sessions, signals[:1]), baseline, check_exact=True)
    assert_frame_equal(run(monthly.reverse(), sessions, signals[:1]), baseline, check_exact=True)


def test_cross_sectional_demeaning_preserves_all_three_complete_cohort_ranks():
    monthly, sessions, signals = fixture()
    demeaned = monthly.with_columns((pl.col('monthly_return') - pl.col('monthly_return').mean().over('trade_date')).alias('monthly_return'))
    a, b = run(monthly, sessions, signals), run(demeaned, sessions, signals)
    for name in SEASONALITY_NAMES:
        rank = lambda x: x.select(pl.col(name).rank().over('trade_date'))
        assert_frame_equal(rank(a), rank(b), check_exact=True)


def test_calendar_endpoints_no_stale_fill_split_adjustment_and_zero_volume():
    _, sessions, _ = fixture()
    dates = [dt.date(2019,1,31), dt.date(2019,2,28), dt.date(2019,4,30),dt.date(2019,5,31)]
    bars = pl.DataFrame({'symbol':['A']*4,'trade_date':dates,'close':[100.,50.,55.,60.],
                         'adj_factor':[1.,2.,2.,2.],'volume':[100.,100.,0.,100.]})
    result = calendar_month_returns(bars,sessions=sessions).filter(pl.col('trade_date').dt.year()==2019)
    assert result['monthly_return'].to_list() == [None,0.,None,None,None]


def test_partial_last_calendar_month_does_not_become_endpoint():
    _, sessions, _ = fixture()
    sessions=tuple(d for d in sessions if d <= dt.date(2020,3,13))
    bars=pl.DataFrame({'symbol':['A']*3,'trade_date':[dt.date(2020,1,31),dt.date(2020,2,28),dt.date(2020,3,13)],
                       'close':[10.,11.,12.],'adj_factor':[1.,1.,1.],'volume':[1.,1.,1.]})
    result=calendar_month_returns(bars,sessions=sessions)
    assert result['trade_date'].max()==dt.date(2020,2,28)


def test_insufficient_history_status_is_not_truncated_or_backfilled():
    monthly,sessions,_=fixture()
    signal=dt.date(2012,1,31)
    result=run(monthly,sessions,(signal,))
    assert result['status'].unique().to_list()==['insufficient_history']
    assert result[SEASONALITY_NAMES[0]].null_count()==result.height


@pytest.mark.parametrize('case', ['duplicate','not_month_end','duplicate_signal','unordered_calendar','missing_calendar_month'])
def test_invalid_input_keys_calendar_and_publication(case):
    monthly,sessions,signals=fixture()
    if case=='duplicate':monthly=pl.concat([monthly,monthly.head(1)])
    if case=='not_month_end':signals=(dt.date(2021,1,28),)
    if case=='duplicate_signal':signals=(signals[0],signals[0])
    if case=='unordered_calendar':sessions=tuple(reversed(sessions))
    if case=='missing_calendar_month':sessions=tuple(d for d in sessions if not(d.year==2018 and d.month==2))
    with pytest.raises(ValueError):run(monthly,sessions,signals)
