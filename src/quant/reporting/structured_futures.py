"""Observed IF/IC/IM quotes for the monthly market panel, never a timing signal."""
import datetime as dt
from pathlib import Path

import polars as pl


def market_facts(month, *, root=Path('.'), known_at=None):
    clock = known_at or dt.datetime.now(dt.timezone.utc)
    if clock.tzinfo is None:
        raise ValueError('Require zoned knowledge cutoff')
    files = sorted((Path(root)/'data/clean/fut_daily').glob('snapshot=d2_*/data.parquet'))
    out = {'status': 'not_captured', 'month': month, 'consumer': 'monthly_market_panel_only',
           'basis_status': 'unknown_no_matching_spot_series', 'rows': [], 'auto_trade': False,
           'known_at': clock.isoformat(), 'sources': list(map(str, files))}
    if not files:
        return out
    frames = [pl.scan_parquet(p).filter(pl.col('trade_date').str.starts_with(month.replace('-', '')) &
               (pl.col('available_at') <= clock)).collect() for p in files]
    data = pl.concat(frames, how='diagonal_relaxed').sort('available_at').unique(
        ['ts_code', 'trade_date'], keep='last')
    if data.is_empty():
        out['status'] = 'no_observed_rows_in_month'
        return out
    latest = data['trade_date'].max()
    out.update(status='observed_quotes', latest_date=latest,
               rows=data.filter(pl.col('trade_date') == latest).select(
                   'ts_code', 'trade_date', 'close', 'settle', 'vol', 'oi', 'native_units').sort('ts_code').to_dicts())
    return out
