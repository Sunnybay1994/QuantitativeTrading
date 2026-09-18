"""Read local daily/minute observations for shadow execution; never refresh data."""
import datetime as dt
from pathlib import Path

import polars as pl

from quant.data.intraday_bars import SCHEMA
from quant.data.publish_cross_asset_etfs import read_cross_asset_etfs
from quant.data.refresh_stocks import read_stock_data

DAILY_SCHEMA = {'symbol': pl.String, 'trade_date': pl.Date, 'open': pl.Float64}


def read_inputs(*, orders: pl.DataFrame, known_through: dt.date, data_root: Path,
        refresh_config: Path, etf_snapshot: str | None = None, minute_source: str = 'baostock',
        frequency: str = '5m', etf_minute_source: str = 'yahoo') -> tuple[pl.DataFrame, pl.DataFrame, list[dict]]:
    if etf_minute_source not in ('yahoo', 'tdx'):
        raise ValueError('Unsupported ETF minute source')
    if frequency not in ('1m', '5m') or minute_source not in ('baostock', 'tdx', 'yahoo', 'futu'):
        raise ValueError('Unsupported explicit local minute source/frequency')
    ready = orders.filter(pl.col('execution_date') <= known_through)
    daily: list[pl.DataFrame] = []
    minutes: list[pl.DataFrame] = []
    errors: list[dict] = []
    if ready.is_empty():
        return pl.DataFrame(schema=DAILY_SCHEMA), pl.DataFrame(schema=SCHEMA), errors
    start = min(ready['execution_date'].to_list())
    for asset in ('stock', 'etf'):
        symbols = sorted(set(ready.filter(pl.col('asset_type') == asset)['symbol']))
        if not symbols:
            continue
        try:
            if asset == 'stock':
                frame = read_stock_data(data_root=data_root, config=refresh_config, table='bar_1d',
                    start=start, end=known_through, symbols=symbols)
            else:
                frame = read_cross_asset_etfs(data_root, etf_snapshot or f'b20_forward_{known_through:%Y%m%d}')['bars']
            daily.append(frame.filter(pl.col('symbol').is_in(symbols)
                & pl.col('trade_date').is_between(start, known_through)).select(list(DAILY_SCHEMA)))
        except Exception as exc:
            errors.append({'asset_type': asset, 'input': 'daily', 'error': f'{type(exc).__name__}: {exc}'})
    for asset, symbol in sorted(set(ready.select('asset_type', 'symbol').iter_rows())):
        if len(symbol) != 9 or not symbol[:6].isdigit() or symbol[6:] not in ('.SH', '.SZ', '.BJ'):
            errors.append({'symbol': symbol, 'input': 'minute', 'error': 'Unsupported symbol'})
            continue
        # ETF accumulation uses Yahoo 1m; BaoStock covers the stock universe only.
        source, freq = (etf_minute_source, '1m') if asset == 'etf' else (minute_source, frequency)
        path = data_root/'clean/bar_intraday'/f'freq={freq}'/f'source={source}'/f'symbol={symbol}'/'data.parquet'
        try:
            frame = pl.scan_parquet(path).filter(pl.col('trade_date').is_between(start, known_through)).collect()
            if set(frame['symbol'])- {symbol}:
                raise ValueError('Minute partition contains another symbol')
            minutes.append(frame.select(list(SCHEMA)))
        except Exception as exc:
            errors.append({'symbol': symbol, 'input': 'minute', 'source': source,
                'frequency': freq, 'error': f'{type(exc).__name__}: {exc}'})
    return (pl.concat(daily, how='vertical_relaxed') if daily else pl.DataFrame(schema=DAILY_SCHEMA),
        pl.concat(minutes, how='vertical_relaxed') if minutes else pl.DataFrame(schema=SCHEMA), errors)
