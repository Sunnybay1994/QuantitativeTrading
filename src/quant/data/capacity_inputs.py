"""Recover missing ADV from saved daily bars with a full exchange-session window."""
import datetime as dt
from pathlib import Path

import polars as pl

from quant.data.factor_panels import available_sessions
from quant.data.refresh_stocks import read_stock_data


def calculate_adv(keys: pl.DataFrame, bars: pl.DataFrame, sessions: tuple[dt.date, ...]) -> pl.DataFrame:
    if bars.select('symbol', 'trade_date').is_duplicated().any():
        raise ValueError('Duplicate daily liquidity observations')
    rows = []
    for key in keys.unique().iter_rows(named=True):
        day, symbol = key['as_of'], key['symbol']
        window = [s for s in sessions if s <= day][-20:]
        selected = bars.filter((pl.col('symbol') == symbol) & pl.col('trade_date').is_in(window))
        good = (len(window) == 20 and selected.height == 20 and not selected['amount'].null_count()
                and selected['amount'].is_finite().all() and (selected['amount'] >= 0).all())
        value = sum(float(v) for v in selected['amount'])/20 if good else None
        rows.append({**key, 'recovered_adv20': value if value is not None and value > 0 else None,
            'observed_sessions': selected.height})
    return pl.from_dicts(rows, schema={'symbol': pl.String, 'as_of': pl.Date,
        'recovered_adv20': pl.Float64, 'observed_sessions': pl.Int64})


def read_missing_adv(keys: pl.DataFrame, data_root: Path, refresh_config: Path) -> pl.DataFrame:
    end = max(keys['as_of'].to_list())
    sessions = available_sessions(data_root, end)
    first = min(keys['as_of'].to_list())
    history = [s for s in sessions if s <= first][-20:]
    bars = read_stock_data(data_root=data_root, config=refresh_config, table='bar_1d',
        start=history[0], end=end, symbols=sorted(set(keys['symbol'])))
    return calculate_adv(keys, bars, sessions)
