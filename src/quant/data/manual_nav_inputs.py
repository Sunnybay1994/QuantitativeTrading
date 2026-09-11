"""Read saved daily inputs for manual account closing; never fetch data here."""
import datetime as dt
import tomllib
from pathlib import Path

import polars as pl

from quant.data.refresh_stocks import read_stock_data
from quant.data.stock_paper_inputs import read_stock_paper_calendar


def read_manual_nav_inputs(*, data_root: Path, config: Path, symbols: list[str],
                           date: dt.date) -> dict[str, pl.DataFrame]:
    settings = tomllib.loads(config.read_text(encoding='utf-8'))
    folder = data_root/'clean/stock_paper_inputs'/f'date={date}'
    bars = read_stock_data(data_root=data_root, config=Path(settings['data']['refresh_config']),
                          table='bar_1d', start=date, end=date, symbols=symbols)
    dividends = pl.read_parquet(folder/'dividends.parquet').with_columns(
        (pl.col('div_cash') * (1-settings['portfolio']['stock_dividend_withholding'])).alias('div_cash'))
    return {'bars': bars, 'calendar': read_stock_paper_calendar(data_root), 'dividends': dividends,
            'suspensions': pl.read_parquet(folder/'suspensions.parquet')}
