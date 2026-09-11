import datetime as dt

import pytest

from quant.research.run_calendar_annual_model import annual_windows


def case():
    sessions = (dt.date(2022, 12, 30), dt.date(2023, 1, 3), dt.date(2023, 12, 29),
                dt.date(2024, 1, 2), dt.date(2024, 12, 31))
    fits = [{'test_year': 2023, 'factors': []}, {'test_year': 2024, 'factors': ['a'],
             'refit_close': '2023-12-29', 'last_known_exit': '2023-12-01'}]
    return dict(fits=fits, sessions=sessions, start=dt.date(2023, 1, 1), end=dt.date(2024, 12, 31))


def test_adjacent_fits_do_not_overlap_and_final_close_is_retained():
    plan = annual_windows(**case())
    assert plan[0]['cutoff'] == dt.date(2022, 12, 30)
    assert plan[0]['source_factors'] == []
    assert plan[0]['end'] < plan[1]['cutoff']
    assert plan[1]['cutoff'] == dt.date(2023, 12, 29)
    assert plan[1]['end'] == dt.date(2024, 12, 31)


@pytest.mark.parametrize('change', ['missing_year', 'duplicate_year', 'cutoff', 'future_label'])
def test_incomplete_or_noncausal_source_fits_fail(change):
    args = case()
    if change == 'missing_year':
        args['fits'] = args['fits'][1:]
    elif change == 'duplicate_year':
        args['fits'].append(args['fits'][0])
    elif change == 'cutoff':
        args['fits'][1]['refit_close'] = '2023-12-28'
    else:
        args['fits'][1]['last_known_exit'] = '2024-01-02'
    with pytest.raises(ValueError):
        annual_windows(**args)
