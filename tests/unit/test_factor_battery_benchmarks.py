import datetime as dt

import polars as pl
import pytest

from quant.research.factor_battery_benchmarks import equal_weight_targets


def test_benchmark_uses_only_known_members_and_signal_eligibility():
    january, february = dt.date(2020, 1, 31), dt.date(2020, 2, 28)
    sessions = (january, dt.date(2020, 2, 3), february, dt.date(2020, 3, 2))
    universe = pl.DataFrame({'trade_date': [january]*3+[february]*3, 'symbol': ['a', 'b', 'c']*2,
                            'eligible': [True, True, False, True, True, True]})
    members = pl.DataFrame({'snapshot_date': [january, dt.date(2020, 2, 10)], 'symbol': ['a', 'b']})
    kwargs = dict(signals=[january, february], sessions=sessions, end=sessions[-1], name='benchmark')
    result = equal_weight_targets(universe, members=members, **kwargs)
    assert result['symbol'].to_list() == ['a', 'b']
    assert result['weight'].to_list() == [1., 1.]
    assert result['execution_date'].to_list() == [sessions[1], sessions[3]]
    broad = equal_weight_targets(universe, members=None, **kwargs)
    assert broad.filter(pl.col('as_of') == january)['symbol'].to_list() == ['a', 'b']
    assert broad.filter(pl.col('as_of') == january)['weight'].to_list() == [.5, .5]
    assert broad.filter(pl.col('as_of') >= pl.col('execution_date')).is_empty()
    with pytest.raises(ValueError, match='Missing historical'):
        equal_weight_targets(universe, members=members.tail(1), **kwargs)


def test_empty_benchmark_cannot_silently_retain_old_targets():
    signal = dt.date(2020, 1, 31)
    universe = pl.DataFrame({'trade_date': [signal], 'symbol': ['a'], 'eligible': [False]})
    with pytest.raises(ValueError, match='Empty executable'):
        equal_weight_targets(universe, members=None, signals=[signal],
                             sessions=(signal, dt.date(2020, 2, 3)), end=dt.date(2020, 2, 3), name='benchmark')
