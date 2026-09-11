import datetime as dt

import polars as pl

from quant.research.run_multifactor_replay import model_signal_coverage


def test_refit_signal_and_missing_month_use_execution_year():
    dates = tuple(dt.date.fromisoformat(x) for x in (
        '2025-12-31', '2026-01-05', '2026-01-30', '2026-02-02',
        '2026-02-27', '2026-03-02', '2026-03-31', '2026-04-01'))
    scores = pl.DataFrame({'symbol': ['A', 'B', 'A', 'B'],
                          'trade_date': [dates[0]]*2 + [dates[2]]*2})
    model = {'walk_forward': {'test_start': dt.date(2026, 1, 1),
                             'test_end': dt.date(2026, 3, 31)},
             'models': {'minimum_signal_stocks': 2}}
    result = model_signal_coverage(scores, annual_fits=[{'test_year': 2026}],
                                   model=model, sessions=dates)
    assert result['test_year'].to_list() == [2026]*3
    assert result['signal_date'].to_list() == [dates[0], dates[2], dates[4]]
    assert result['available_stocks'].to_list() == [2, 2, 0]
    assert result['reason'].to_list() == ['available', 'available', 'insufficient_complete_feature_rows']


def test_cash_training_year_is_distinct_from_missing_common_features():
    scores = pl.DataFrame(schema={'symbol': pl.String, 'trade_date': pl.Date})
    model = {'walk_forward': {'test_start': dt.date(2020, 1, 1),
                             'test_end': dt.date(2020, 1, 31)},
             'models': {'minimum_signal_stocks': 2}}
    result = model_signal_coverage(scores,
        annual_fits=[{'test_year': 2020, 'reason': 'no_admitted_factors'}], model=model,
        sessions=(dt.date(2019, 12, 31), dt.date(2020, 1, 2)))
    assert result['reason'].to_list() == ['no_admitted_factors']
    assert result['signal_available'].to_list() == [False]
