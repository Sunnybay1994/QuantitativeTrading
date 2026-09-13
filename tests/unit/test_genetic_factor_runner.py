import datetime as dt

import polars as pl

from quant.research.run_genetic_factor_search import assess, split_panel


def test_split_excludes_unmatured_and_invalid_labels():
    panel = pl.DataFrame({
        'trade_date': [dt.date(2020, 12, 1)] * 3,
        'label_exit_date': [dt.date(2020, 12, 30), dt.date(2021, 1, 4), dt.date(2020, 11, 1)],
        'symbol': ['A', 'B', 'C'],
    })
    result = split_panel(panel, dt.date(2020, 1, 1), dt.date(2020, 12, 31))
    assert result['symbol'].to_list() == ['A']


def test_assess_uses_within_date_ranks_and_frozen_direction():
    # Cross-date level shifts dominate flattened correlation but are irrelevant to IC.
    panel = pl.DataFrame({
        'trade_date': [dt.date(2020, 1, 31)] * 3 + [dt.date(2020, 2, 28)] * 3,
        'symbol': ['A', 'B', 'C'] * 2,
        'x': [1., 2., 3., 101., 102., 103.],
        'label': [3., 2., 1., 103., 102., 101.],
    })
    result = assess(panel, {'terminal_expression': 'x', 'direction': -1}, 3)
    assert result['months'] == 2
    assert abs(result['mean_ic'] - 1.) < 1e-12
