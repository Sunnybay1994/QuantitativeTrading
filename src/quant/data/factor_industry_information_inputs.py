"""Exact month-end inputs for the registered, frozen-taxonomy industry family."""
import datetime as dt
from pathlib import Path
import tomllib

import polars as pl

from quant.data.industry_history import attach_industry
from quant.data.refresh_stocks import read_stock_data
from quant.factors.industry_information import compute_industry_information

DEFINITION = Path('configs/research/industry_information_family_v1.toml')


def read_industry_information(*, data_root: Path, refresh_config: Path,
        calendar: tuple[dt.date, ...], start: dt.date, end: dt.date,
        definition: Path = DEFINITION) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    spec = tomllib.loads(definition.read_text(encoding='utf-8'))
    anchors = tuple(a for a,b in zip(calendar,calendar[1:]) if (a.year,a.month)!=(b.year,b.month))
    wanted = tuple(d for d in anchors if start <= d <= end)
    if not wanted:
        raise ValueError('Industry information requires a completed monthly anchor')
    position=anchors.index(wanted[0])
    if position < 6:
        raise ValueError('Industry information calendar needs six preceding month ends')
    months=tuple(d for d in anchors[position-6:] if d<=wanted[-1])
    bars,basic=[],[]
    for year in range(months[0].year,months[-1].year+1):
        low,high=max(months[0],dt.date(year,1,1)),min(months[-1],dt.date(year,12,31))
        bars.append(read_stock_data(data_root=data_root,config=refresh_config,table='bar_1d',
            start=low,end=high,columns=('symbol','trade_date','close','adj_factor','volume')).filter(pl.col('trade_date').is_in(months)))
        basic.append(read_stock_data(data_root=data_root,config=refresh_config,table='daily_basic',
            start=low,end=high,columns=('symbol','trade_date','total_market_value')).filter(pl.col('trade_date').is_in(months)))
    panel=attach_industry(pl.concat(bars).join(pl.concat(basic),on=['symbol','trade_date'],how='left',validate='1:1'),
        pl.read_parquet(data_root/'clean/tushare_industry'/spec['initial_industry_snapshot']/'intervals.parquet'))
    values,diagnostics=compute_industry_information(panel,month_ends=months)
    return values.filter(pl.col('trade_date').is_in(wanted)),diagnostics.filter(pl.col('trade_date').is_in(wanted)),panel
