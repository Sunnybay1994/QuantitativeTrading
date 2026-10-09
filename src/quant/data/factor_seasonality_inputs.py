"""Calendar-month endpoints for the fixed years-two-to-five return family."""
import datetime as dt
from pathlib import Path

import polars as pl

from quant.data.refresh_stocks import read_stock_data
from quant.factors.return_seasonality import calendar_month_returns


def seasonality_price_start(first_signal: dt.date) -> dt.date:
    # Signal M forecasts M+1. Earliest return is M-59, needing price at M-60.
    month = first_signal.year * 12 + first_signal.month - 1 - 60
    return dt.date(month // 12, month % 12 + 1, 1)


def read_seasonality_returns(*, data_root: Path, refresh_config: Path,
                            calendar: tuple[dt.date, ...], start: dt.date, end: dt.date) -> pl.DataFrame:
    low = seasonality_price_start(start)
    ends = [a for a,b in zip(calendar,calendar[1:])
            if (a.year,a.month)!=(b.year,b.month) and low<=a<=end]
    parts=[]
    for year in range(low.year,end.year+1):
        bars=read_stock_data(data_root=data_root,config=refresh_config,table='bar_1d',
            start=max(low,dt.date(year,1,1)),end=min(end,dt.date(year,12,31)),
            columns=('symbol','trade_date','close','adj_factor','volume'))
        parts.append(bars.filter(pl.col('trade_date').is_in(ends)).select(
            'symbol','trade_date','close','adj_factor','volume'))
    endpoints=pl.concat(parts)
    return calendar_month_returns(endpoints,sessions=tuple(d for d in calendar if d>=low))
