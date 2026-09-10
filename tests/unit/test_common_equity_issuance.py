import datetime as dt

import polars as pl
import pytest

from quant.factors.common_equity_issuance import compute_no_common_equity_issue


def evaluate(codes: list[str], announcements: list[dt.date], *, as_of: dt.date = dt.date(2024, 4, 4),
             empty: bool = False, start: dt.date = dt.date(2019, 1, 1), end: dt.date = dt.date(2023, 12, 31)):
    events = pl.DataFrame({'symbol': ['A'] * len(codes), 'event_date': [dt.date(2023, 12, 1)] * len(codes),
        'ann_date': announcements, 'change_type_codes': codes}, schema={
            'symbol': pl.String, 'event_date': pl.Date, 'ann_date': pl.Date, 'change_type_codes': pl.String})
    coverage = pl.DataFrame({'symbol': ['A'], 'start': [start], 'end': [dt.date(2026, 9, 10)], 'empty_response': [empty]})
    anchors = pl.DataFrame({'symbol': ['A'], 'end_date': [end]})
    return compute_no_common_equity_issue(events, coverage, anchors, as_of=as_of).row(0, named=True)


def test_bonus_shares_are_not_issuance_and_late_notice_is_not_used_early():
    codes = ['015010,015011', '015004']
    announcements = [dt.date(2023, 12, 1), dt.date(2024, 4, 3)]
    assert evaluate(codes, announcements, as_of=dt.date(2024, 4, 3))['no_common_equity_issue'] == 1
    assert evaluate(codes, announcements)['no_common_equity_issue'] == 0


def test_unknown_event_stays_missing_unless_actual_issuance_is_known():
    day = dt.date(2023, 12, 1)
    result = evaluate(['015025'], [day])
    assert result['no_common_equity_issue'] is None
    assert result['issuance_status'] == 'AMBIGUOUS_CAPITAL_CHANGE'
    assert evaluate(['015025,015005'], [day])['no_common_equity_issue'] == 0


def test_absent_or_partial_request_does_not_mean_no_issuance():
    day = dt.date(2023, 12, 1)
    assert evaluate([], [])['no_common_equity_issue'] is None
    assert evaluate(['015019'], [day], empty=True)['no_common_equity_issue'] is None
    assert evaluate(['015019'], [day], start=dt.date(2023, 6, 1))['no_common_equity_issue'] is None
    with pytest.raises(ValueError, match='completed annual'):
        evaluate(['015019'], [day], end=dt.date(2023, 6, 30))
