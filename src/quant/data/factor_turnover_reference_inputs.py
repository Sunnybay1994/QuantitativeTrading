"""Thin, pinned five-year daily inputs for the registered turnover-reference family."""
import datetime as dt
from pathlib import Path

import polars as pl

from quant.data.refresh_stocks import read_stock_data
from quant.factors.turnover_reference import compute_turnover_reference, formation_dates, SCHEMA


def turnover_reference_start(first_signal: dt.date) -> dt.date:
    return formation_dates(first_signal)[0]


def read_turnover_reference(*, data_root: Path, refresh_config: Path,
                           calendar: tuple[dt.date, ...], start: dt.date, end: dt.date) -> pl.DataFrame:
    signals = tuple(a for a, b in zip(calendar, calendar[1:])
        if (a.year, a.month) != (b.year, b.month) and start <= a <= end)
    if not signals:
        return pl.DataFrame(schema=SCHEMA)
    low = turnover_reference_start(signals[0])
    bars, basic = [], []
    for year in range(low.year, end.year+1):
        first, last = max(low, dt.date(year, 1, 1)), min(end, dt.date(year, 12, 31))
        bars.append(read_stock_data(data_root=data_root, config=refresh_config, table='bar_1d',
            start=first, end=last, columns=('symbol', 'trade_date', 'close', 'adj_factor', 'volume')))
        basic.append(read_stock_data(data_root=data_root, config=refresh_config, table='daily_basic',
            start=first, end=last, columns=('symbol', 'trade_date', 'total_shares')))
    return compute_turnover_reference(pl.concat(bars), pl.concat(basic), sessions=calendar, signal_dates=signals)
