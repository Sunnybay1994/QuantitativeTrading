import datetime as dt

import polars as pl
import pytest

from quant.portfolio.capacity_limits import cap_targets


def test_caps_keep_targets_and_missing_liquidity_halts_execution():
    day = dt.date(2026, 9, 11)
    targets = pl.DataFrame({'symbol': ['A', 'B'], 'as_of': [day]*2,
        'execution_date': [dt.date(2026, 9, 14)]*2, 'weight': [.5, 0.]})
    state = {'date': str(day), 'holdings': {'B': {'quantity': 100}, 'C': {'quantity': 100}}}
    market = pl.DataFrame({'symbol': ['A'], 'as_of': [day], 'amount20': [10000.]})
    result, info = cap_targets(targets, state, market)
    assert result.equals(targets)
    assert info['execution_notional_caps'] == {'A': 500., 'B': 0., 'C': 0.}
    assert info['missing_adv_symbols'] == ['B', 'C']
    with pytest.raises(ValueError):
        cap_targets(targets, state, market.with_columns(pl.lit(dt.date(2026, 9, 14)).alias('as_of')))
