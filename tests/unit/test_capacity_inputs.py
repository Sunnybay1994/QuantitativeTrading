import datetime as dt

import polars as pl

from quant.data.capacity_inputs import calculate_adv


def test_adv_requires_all_sessions_and_excludes_future():
    days = tuple(dt.date(2026, 1, 1)+dt.timedelta(days=i) for i in range(21))
    keys = pl.DataFrame({'symbol': ['A'], 'as_of': [days[19]]})
    bars = pl.DataFrame({'symbol': ['A']*21, 'trade_date': days, 'amount': [100.]*20+[1e9]})
    full = calculate_adv(keys, bars, days)
    assert full['recovered_adv20'][0] == 100.
    missing = calculate_adv(keys, bars.filter(pl.col('trade_date') != days[5]), days)
    assert missing['recovered_adv20'][0] is None
    assert missing['observed_sessions'][0] == 19
