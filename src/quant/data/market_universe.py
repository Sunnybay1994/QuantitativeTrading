"""Data acquisition membership, independent of any research selection."""
import datetime as dt
import json
import tomllib
from pathlib import Path

import polars as pl


def members(root: Path) -> list[dict]:
    from quant.data.connectors.public_market import PublicMarket
    from quant.data.recent_minutes import universe
    client = PublicMarket(timeout=60)
    try:
        current = universe(client, Path('artifacts/minute_refresh'), root)
    finally:
        client.close()
    result = {row['symbol']: dict(row) for row in current}
    settings = tomllib.loads(Path('configs/data/refresh.toml').read_text(encoding='utf-8'))
    folder = root/'clean/tushare_bulk/snapshots'/settings['stock_snapshot']/'bar_1d/asset=stock'
    history = pl.scan_parquet(str(folder/'year=*/*.parquet')).group_by('symbol').agg(
        pl.col('trade_date').min().alias('first'), pl.col('trade_date').max().alias('last')).collect()
    for row in history.iter_rows(named=True):
        # Retain historical/delisted names; first stored date is not a listing date.
        result.setdefault(row['symbol'], dict(symbol=row['symbol'], asset='stock', name='',
            list_date='19901219', historical_only=True, last_stored_date=str(row['last'])))
    return sorted(result.values(), key=lambda row: row['symbol'])


def listing(row: dict) -> dt.date:
    value = str(row.get('list_date') or '19901219').replace('-', '')
    return dt.datetime.strptime(value, '%Y%m%d').date()


def bao_members(root: Path) -> list[dict]:
    # Other venues stay in the full-market 1m/TDX queue; don't invent BaoStock support.
    from quant.data.connectors.public_market import PublicMarket
    from quant.data.realtime_store import atomic_json
    from quant.data.storage import RawStore
    result = {row['symbol']: row for row in members(root) if row['symbol'].endswith(('.SH', '.SZ'))}
    cache = Path('artifacts/baostock_history/catalog.json')
    saved = json.loads(cache.read_text(encoding='utf-8')) if cache.exists() else {}
    now = dt.datetime.now(dt.timezone.utc)
    if not saved or (now-dt.datetime.fromisoformat(saved['captured_at'])).days >= 1:
        client = PublicMarket(timeout=60)
        try:
            frame = pl.DataFrame(client.fetch('baostock_catalog', [], 'baostock'))
            if frame.is_empty():
                raise ValueError('Empty BaoStock instrument catalog')
            raw = RawStore(root/'raw').write(source='baostock', table='instruments', frame=frame, parameters={})
            saved = dict(captured_at=now.isoformat(), rows=frame.to_dicts(), raw=str(raw.data_path))
            atomic_json(cache, saved)
            atomic_json(cache.with_name('catalog_status.json'), dict(status='fresh', checked_at=now.isoformat()))
        except Exception as exc:
            atomic_json(cache.with_name('catalog_status.json'), dict(status='fallback', checked_at=now.isoformat(),
                error=str(exc), message='Using Tushare current names, stored historical names and cached BaoStock catalog'))
        finally:
            client.close()
    for row in saved.get('rows', []):
        code = row['code']
        if not code.startswith(('sh.6', 'sz.0', 'sz.3')):
            continue
        market, number = code.split('.')
        symbol = f'{number}.{market.upper()}'
        member = result.setdefault(symbol, dict(symbol=symbol, name=row['code_name'], asset='stock'))
        if row.get('ipoDate'):
            member['list_date'] = row['ipoDate']
        if row.get('outDate'):
            member['delist_date'] = row['outDate']
    return sorted(result.values(), key=lambda row: row['symbol'])
