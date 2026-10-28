import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from quant.data import post_close_k1m, us_sessions

SH = ZoneInfo('Asia/Shanghai')


@pytest.mark.parametrize(('clock', 'session'), [
    ('2026-11-27T06:00:00', '2026-11-25'),  # Thanksgiving was closed.
    ('2026-11-28T06:00:00', '2026-11-27'),  # Early close, not a holiday.
    ('2026-07-04T06:00:00', '2026-07-02'),  # Independence Day observed.
    ('2026-03-10T04:04:00', '2026-03-06'),  # DST: settle window not finished.
    ('2026-03-10T04:05:00', '2026-03-09'),
    ('2026-11-03T05:04:00', '2026-10-30'),  # Standard time after Nov 1.
    ('2026-11-03T05:05:00', '2026-11-02'),
])
def test_last_published_completed_session(clock, session):
    now = dt.datetime.fromisoformat(clock).replace(tzinfo=SH)
    assert post_close_k1m.latest_market_session(
        'us', data_root=Path('unused'), through=now.date(), now=now) == dt.date.fromisoformat(session)


def test_cutoff_holiday_and_published_calendar_bounds():
    now = dt.datetime(2026, 11, 28, 6, tzinfo=SH)
    assert us_sessions.latest_closed(through=dt.date(2026, 11, 26), now=now) == dt.date(2026, 11, 25)
    assert us_sessions.expected_bars(dt.date(2026, 11, 26)) == 0
    assert us_sessions.expected_bars(dt.date(2026, 11, 27)) == 210
    assert us_sessions.expected_bars(dt.date(2026, 12, 31)) == 390
    # NYSE explicitly does not observe Jan 1 2028 on Friday Dec 31 2027.
    assert us_sessions.expected_bars(dt.date(2027, 12, 31)) == 390
    with pytest.raises(ValueError, match='does not cover'):
        us_sessions.expected_bars(dt.date(2029, 1, 2))
    with pytest.raises(ValueError, match='aware'):
        us_sessions.latest_closed(through=dt.date(2026, 11, 26), now=now.replace(tzinfo=None))


def test_early_close_expected_count_and_clean_flag():
    day = dt.date(2026, 11, 27)
    begin = dt.datetime.combine(day, dt.time(9, 31))
    rows = []
    for index in range(210):
        rows.append({'code': 'US.SPY', 'time_key': str(begin+dt.timedelta(minutes=index)),
                     'open': 10., 'high': 11., 'low': 9., 'close': 10.,
                     'volume': 100., 'turnover': 1000.})
    # A late-session packet is not a regular cash-session bar on this date.
    rows.append({**rows[-1], 'time_key': '2026-11-27 13:01:00'})
    clean, rejected = post_close_k1m.normalize(rows, 'SPY.US', day)
    assert rejected == 1 and clean.height == 210
    assert clean['session_complete'].all()
    assert post_close_k1m.expected_bars_for('SPY.US', day, Path('unused')) == 210
    holiday, rejected = post_close_k1m.normalize(
        [{**rows[0], 'time_key': '2026-11-26 09:31:00'}], 'SPY.US', day)
    assert holiday.is_empty() and rejected == 1
