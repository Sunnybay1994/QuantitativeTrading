"""Mainland session clock and the current paper holdings/orders watch list."""

import datetime as dt
import re
import tomllib
from pathlib import Path

import polars as pl

TZ = dt.timezone(dt.timedelta(hours=8))


def load_config(path: Path) -> dict:
    settings = tomllib.loads(path.read_text(encoding='utf-8'))
    if settings.get('auto_trade') is not False:
        raise ValueError('Realtime data capture requires auto_trade=false')
    if not 1 <= settings['max_symbols'] <= 40:
        raise ValueError('max_symbols must be within 1..40')
    if settings['quote_poll_seconds'] < 5 or settings['bar_poll_seconds'] < 60:
        raise ValueError('Quote polling >=5 seconds and bar polling >=60 seconds required')
    if settings['confirmation_seconds'] < 63:
        raise ValueError('Provider-labelled bars require conservative 63-second confirmation')
    if settings['quota_reserve'] < 0:
        raise ValueError('quota_reserve cannot be negative')
    return settings


def phase(now: dt.datetime) -> str:
    t = now.astimezone(TZ).time()
    if t < dt.time(9, 20):
        return 'before_start'
    if t < dt.time(9, 30):
        return 'preopen'
    if t < dt.time(11, 30):
        return 'trading'
    if t < dt.time(11, 33):
        return 'settling'
    if t < dt.time(13):
        return 'lunch'
    if t < dt.time(15):
        return 'trading'
    if t < dt.time(15, 5):
        return 'settling'
    return 'closed'


def watchlist(settings: dict, date: dt.date, *, previous_session: dt.date | None = None) -> dict:
    holdings, orders = set(), set()
    sources = []
    for folder in settings.get('account_roots', []):
        root = Path(folder)
        dated = sorted(p for p in root.glob('????-??-??')
                       if p.is_dir() and p.name <= str(date))
        if not dated:
            raise ValueError(f'No saved account session in {root}')
        latest = dated[-1]
        if previous_session is not None and latest.name < str(previous_session):
            raise ValueError(f'Stale account snapshot: {latest}; need {previous_session} or later')
        sources.append(str(latest))
        p = latest / 'positions.csv'
        if not p.exists():
            raise ValueError(f'Missing positions: {p}')
        frame = pl.read_csv(p)
        if frame.height:
            holdings.update(frame.filter(pl.col('quantity') > 0)['symbol'].to_list())
        p = latest / 'orders.csv'
        if p.exists():
            frame = pl.read_csv(p)
            if frame.height:
                orders.update(frame.filter(pl.col('execution_date').cast(pl.String)
                                            == str(date))['symbol'].to_list())
    mandatory = sorted(holdings | orders)
    representatives = list(settings.get('symbols', []))
    if settings.get('representatives'):
        representatives += tomllib.loads(Path(settings['representatives']).read_text(
            encoding='utf-8'))['symbols']
    candidates = list(dict.fromkeys([*mandatory, *representatives]))
    symbols = candidates[:settings['max_symbols']]
    if any(not re.fullmatch(r'\d{6}\.(SH|SZ)', s) for s in symbols):
        raise ValueError('First release supports only mainland SH/SZ securities')
    if len(mandatory) > settings['max_symbols']:
        raise ValueError(f'Positions/orders have {len(mandatory)} symbols, exceed limit; '
                         'refusing to silently drop positions/orders')
    return {'symbols': symbols, 'holdings': sorted(holdings), 'orders': sorted(orders),
            'sources': sources, 'as_of': str(date), 'omitted_representatives': candidates[len(symbols):]}


def fit_quota(selection: dict, *, remaining: int, reserve: int) -> dict:
    capacity = max(0, (remaining - reserve) // 2)
    mandatory = set(selection.get('holdings', [])) | set(selection.get('orders', []))
    if len(mandatory) > capacity or capacity == 0:
        raise ValueError(f'Realtime quota cannot cover {len(mandatory)} held/order symbols; '
                         f'capacity={capacity}, remaining={remaining}')
    chosen = selection['symbols'][:capacity]
    return {**selection, 'symbols': chosen, 'omitted_representatives':
            selection.get('omitted_representatives', []) + selection['symbols'][capacity:]}


def minute_grid(day: dt.date) -> list[dt.datetime]:
    # Preserve Futu's 241 provider labels, including its separate 09:30 opening row.
    return [dt.datetime.combine(day, dt.time(h, m), TZ)
            for h in range(9, 16) for m in range(60)
            if dt.time(9, 30) <= dt.time(h, m) <= dt.time(11, 30)
            or dt.time(13, 1) <= dt.time(h, m) <= dt.time(15)]
