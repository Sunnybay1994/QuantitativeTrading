"""Load local close-date marks and saved instruments for manual order rehearsal."""
import datetime as dt
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.order_risk_inputs import read_order_risk_inputs
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
