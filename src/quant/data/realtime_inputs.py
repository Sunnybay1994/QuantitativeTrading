"""Mainland session clock and the current paper holdings/orders watch list."""

import datetime as dt
import re
import tomllib
from pathlib import Path

import polars as pl

TZ = dt.timezone(dt.timedelta(hours=8))


# Quote-first: one QUOTE slot per symbol. Hard cap leaves headroom for 100/300-tier remain.
MAX_SYMBOLS_LIMIT = 200


def load_config(path: Path) -> dict:
    settings = tomllib.loads(path.read_text(encoding='utf-8'))
    if settings.get('auto_trade') is not False:
        raise ValueError('Realtime data capture requires auto_trade=false')
    if not 1 <= settings['max_symbols'] <= MAX_SYMBOLS_LIMIT:
        raise ValueError(f'max_symbols must be within 1..{MAX_SYMBOLS_LIMIT}')
    if settings['quote_poll_seconds'] < 5 or settings['bar_poll_seconds'] < 60:
        raise ValueError('Quote polling >=5 seconds and bar polling >=60 seconds required')
    if settings['confirmation_seconds'] < 63:
        raise ValueError('Provider-labelled bars require conservative 63-second confirmation')
    if settings['quota_reserve'] < 0:
        raise ValueError('quota_reserve cannot be negative')
    # Futu releases a slot only after >=60s subscribed; rotation must honour that.
    rotate = settings.setdefault('k1m_rotate_seconds', 65)
    if rotate < 60:
        raise ValueError('k1m_rotate_seconds must be >=60 (OpenD unsubscribe hold)')
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
    """Admit symbols under quote-first budgeting (1 QUOTE slot each).

    Mandatory holdings/orders must fit in ``remaining - reserve``. Leftover slots
    after all admitted QUOTE subscriptions become concurrent K_1M capacity for
    rotation. Representatives may be trimmed; positions/orders are never dropped.
    """
    available = max(0, remaining - reserve)
    mandatory = set(selection.get('holdings', [])) | set(selection.get('orders', []))
    if len(mandatory) > available or available == 0:
        raise ValueError(
            f'Realtime quota cannot cover QUOTE for {len(mandatory)} held/order symbols; '
            f'available={available}, remaining={remaining}, reserve={reserve}')
    chosen = selection['symbols'][:available]
    if mandatory - set(chosen):
        raise ValueError(
            f'Realtime quota cannot cover QUOTE for {len(mandatory)} held/order symbols; '
            f'available={available}, remaining={remaining}, reserve={reserve}')
    k1m_slots = available - len(chosen)
    return {**selection, 'symbols': chosen, 'k1m_slots': k1m_slots,
            'quote_slots': len(chosen),
            'omitted_representatives':
            selection.get('omitted_representatives', []) + selection['symbols'][len(chosen):]}


def next_k1m_batch(symbols: list[str], capacity: int, cursor: int) -> tuple[list[str], int]:
    """Return the next rotating K_1M window and the cursor for the following cycle."""
    if capacity <= 0 or not symbols:
        return [], cursor
    if capacity >= len(symbols):
        return list(symbols), 0
    n = len(symbols)
    start = cursor % n
    batch = [symbols[(start + i) % n] for i in range(capacity)]
    return batch, (start + capacity) % n


def k1m_refresh_seconds(n_symbols: int, k1m_slots: int, rotate_seconds: int) -> int | None:
    """Seconds until each symbol re-enters a K_1M window; None if fully covered or no K slots."""
    if k1m_slots <= 0 or n_symbols <= 0:
        return None
    if k1m_slots >= n_symbols:
        return None
    cycles = (n_symbols + k1m_slots - 1) // k1m_slots
    return cycles * rotate_seconds


def minute_grid(day: dt.date) -> list[dt.datetime]:
    # Preserve Futu's 241 provider labels, including its separate 09:30 opening row.
    return [dt.datetime.combine(day, dt.time(h, m), TZ)
            for h in range(9, 16) for m in range(60)
            if dt.time(9, 30) <= dt.time(h, m) <= dt.time(11, 30)
            or dt.time(13, 1) <= dt.time(h, m) <= dt.time(15)]
