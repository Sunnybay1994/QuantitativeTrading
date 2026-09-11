"""Local signal-date inputs for the stock reference-order risk report."""
import datetime as dt
from pathlib import Path

import polars as pl

from quant.data.factor_panels import available_sessions, read_factor_industry
from quant.data.refresh_stocks import read_stock_data


def read_order_risk_inputs(*, data_root: Path, refresh_config: Path,
                          symbols: list[str], as_of: dt.date,
                          lookback: int) -> tuple[pl.DataFrame, dt.date]:
    if lookback < 1 or len(symbols) != len(set(symbols)):
        raise ValueError('Require unique symbols and a positive liquidity window')
    sessions = available_sessions(data_root, as_of + dt.timedelta(days=40))
    if as_of not in sessions or sessions.index(as_of) + 1 >= len(sessions):
        raise ValueError('Missing signal or next execution session')
    index = sessions.index(as_of)
    history = sessions[max(0, index-lookback+1):index+1]
    if len(history) != lookback:
        raise ValueError('Insufficient liquidity calendar history')
    folder = data_root/'clean/stock_paper_inputs'/f'date={as_of}'
    instruments = pl.read_parquet(folder/'instruments.parquet').select('symbol', 'board_lot')
    bands = pl.read_parquet(folder/'limits.parquet').filter(pl.col('trade_date') == as_of)
    suspensions = pl.read_parquet(folder/'suspensions.parquet').filter(pl.col('trade_date') == as_of)
    bars = read_stock_data(data_root=data_root, config=refresh_config, table='bar_1d',
                          start=history[0], end=as_of, symbols=symbols)
    if bars.select('symbol', 'trade_date').is_duplicated().any():
        raise ValueError('Duplicate risk price inputs')
    values = bars.sort('trade_date').group_by('symbol').agg(
        pl.col('close').last(), pl.col('trade_date').last().alias('price_date'),
        pl.when((pl.len() == lookback) & pl.col('amount').is_finite().all()
                & (pl.col('amount') > 0).all()).then(pl.col('amount').mean())
        .otherwise(None).alias('average_amount'))
    market = pl.DataFrame({'symbol': symbols}, schema={'symbol': pl.String}).with_columns(
        pl.lit(as_of).alias('trade_date')).join(values, on='symbol', how='left', validate='1:1')
    market = market.join(instruments, on='symbol', how='left', validate='1:1').join(
        bands.select('symbol', 'up_limit', 'down_limit'), on='symbol', how='left', validate='1:1')
    market = market.with_columns(pl.col('symbol').is_in(suspensions['symbol'].to_list()).alias('suspended'))
    market = read_factor_industry(data_root, market).rename({'industry_l1': 'industry'})
    return market, sessions[index+1]
