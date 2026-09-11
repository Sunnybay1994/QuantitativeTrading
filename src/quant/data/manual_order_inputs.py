"""Load local close-date marks and saved instruments for manual order rehearsal."""
import datetime as dt
import tomllib
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.order_risk_inputs import read_order_risk_inputs
from quant.data.refresh_stocks import read_stock_data
from quant.data.stock_paper_inputs import StockPaperInputs, read_stock_paper_calendar


def read_manual_order_inputs(*, data_root: Path, settings: dict[str, Any],
                             symbols: list[str], as_of: dt.date
                             ) -> tuple[StockPaperInputs, pl.DataFrame, dt.date]:
    market, next_session = read_order_risk_inputs(data_root=data_root,
        refresh_config=Path(settings['refresh_config']), symbols=symbols,
        as_of=as_of, lookback=settings['liquidity_sessions'])
    instruments = pl.read_parquet(data_root/'clean/stock_paper_inputs'/f'date={as_of}'/'instruments.parquet')
    inputs = StockPaperInputs(bars=market.select('symbol', 'trade_date', 'close'),
        calendar=read_stock_paper_calendar(data_root), instruments=instruments,
        daily_basic=pl.DataFrame(), names=pl.DataFrame(), limits=pl.DataFrame(),
        suspensions=pl.DataFrame(), dividends=pl.DataFrame())
    return inputs, market, next_session


def read_manual_replay_inputs(*, data_root: Path, settings: dict[str, Any],
                              symbols: list[str], as_of: dt.date,
                              execution_date: dt.date) -> StockPaperInputs:
    """Load the later observed session only after signal-close orders are decided."""
    folder = data_root/'clean/stock_paper_inputs'/f'date={execution_date}'
    costs_config = tomllib.loads(Path(settings['cost_config']).read_text(encoding='utf-8'))
    bars = read_stock_data(data_root=data_root, config=Path(settings['refresh_config']),
        table='bar_1d', start=as_of, end=execution_date, symbols=symbols)
    dividends = pl.read_parquet(folder/'dividends.parquet').with_columns(
        (pl.col('div_cash') * (1-costs_config['portfolio']['stock_dividend_withholding'])).alias('div_cash'))
    return StockPaperInputs(bars=bars, calendar=read_stock_paper_calendar(data_root),
        instruments=pl.read_parquet(folder/'instruments.parquet'),
        limits=pl.read_parquet(folder/'limits.parquet'),
        suspensions=pl.read_parquet(folder/'suspensions.parquet'), dividends=dividends,
        daily_basic=pl.DataFrame(), names=pl.DataFrame())
