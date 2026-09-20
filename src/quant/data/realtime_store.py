"""Versioned, available-at-aware local feed for minute strategy readers."""

import datetime as dt
import gzip
import hashlib
import json
import math
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from quant.data.realtime_inputs import TZ, minute_grid, phase


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False),
                   encoding='utf-8')
    tmp.replace(path)


def raw_packet(root: Path, kind: str, rows: list[dict], now: dt.datetime, *, source: str = 'futu') -> str:
    if source not in ('futu', 'tushare_sina', 'akshare_eastmoney', 'akshare_sina'):
        raise ValueError('Unknown feed source')
    folder = root / 'raw' / source / 'realtime' / f'date={now.date()}' / kind
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f'{now:%H%M%S%f}_{uuid.uuid4().hex}.json.gz'
    with path.open('xb') as stream, gzip.GzipFile(fileobj=stream, mode='wb') as zipped:
        zipped.write(json.dumps({'received_at': now.isoformat(), 'kind': kind,
                                'rows': rows}, default=str).encode('utf-8'))
    return str(path)


def symbol_of(code: str) -> str:
    market, code = code.split('.')
    return f'{code}.{market}'


def finite(value, positive=False) -> float:
    v = float(value)
    if not math.isfinite(v) or v < 0 or (positive and v == 0):
        raise ValueError('Invalid price/volume/amount')
    return v


class FeedStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS quotes (
            id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, provider_time TEXT NOT NULL,
            received_at TEXT NOT NULL, payload TEXT NOT NULL, raw_path TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS quote_lookup ON quotes(symbol, received_at, id);
          CREATE TABLE IF NOT EXISTS bars (
            id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, provider_time TEXT NOT NULL,
            available_at TEXT NOT NULL, digest TEXT NOT NULL, payload TEXT NOT NULL,
            raw_path TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS bar_lookup ON bars(symbol, provider_time, available_at, id);
        ''')

    def quotes(self, rows: list[dict], now: dt.datetime, raw: str,
               symbols: list[str]) -> list[dict]:
        errors = []
        with self.db:
            for row in rows:
                try:
                    symbol = symbol_of(row['code'])
                    stamp = dt.datetime.fromisoformat(row['data_date'] + 'T' + row['data_time'])
                    stamp = stamp.replace(tzinfo=TZ)
                    if symbol not in symbols or stamp > now + dt.timedelta(seconds=2):
                        raise ValueError('Unexpected symbol or future quote')
                    value = {'symbol': symbol, 'last_price': finite(row['last_price'], True),
                             'volume': finite(row['volume']), 'amount': finite(row['turnover']),
                             'suspension': bool(row.get('suspension', False)),
                             'provider_time': stamp.isoformat(), 'received_at': now.isoformat(),
                             'source': row.get('source', 'futu')}
                    previous = self.db.execute('SELECT provider_time FROM quotes WHERE symbol=? '
                                               'ORDER BY id DESC LIMIT 1', (symbol,)).fetchone()
                    if previous and previous[0] > stamp.isoformat():
                        continue
                    self.db.execute('INSERT INTO quotes VALUES(NULL,?,?,?,?,?)',
                                    (symbol, stamp.isoformat(), now.isoformat(),
                                     json.dumps(value), raw))
                except (KeyError, ValueError, TypeError) as exc:
                    errors.append({'code': str(row.get('code')), 'error': str(exc)})
        return errors

    def bars(self, rows: list[dict], symbol: str, now: dt.datetime, raw: str,
             confirmation_seconds: int, *, session_date: dt.date | None = None) -> dict:
        errors, added, unfinished = [], 0, 0
        day = session_date or now.date()
        grid = {t.isoformat() for t in minute_grid(day)}
        with self.db:
            for row in rows:
                try:
                    stamp = dt.datetime.fromisoformat(row['time_key']).replace(tzinfo=TZ)
                    if symbol_of(row['code']) != symbol:
                        raise ValueError('Unexpected symbol')
                    if stamp.date() != day:
                        continue
                    if stamp.isoformat() not in grid:
                        raise ValueError('Unexpected mainland minute label')
                    # Re-fetch after a full minute plus grace. Never promote an old live
                    # snapshot merely because the local clock advanced.
                    if stamp + dt.timedelta(seconds=confirmation_seconds) > now:
                        unfinished += 1
                        continue
                    value: dict[str, Any] = {
                        k: finite(row[k], True) for k in ('open', 'high', 'low', 'close')}
                    value.update(volume=finite(row['volume']), amount=finite(row['turnover']))
                    if value['high'] < max(value['open'], value['low'], value['close']) or \
                            value['low'] > min(value['open'], value['high'], value['close']):
                        raise ValueError('Invalid OHLC ordering')
                    value.update(symbol=symbol, provider_time=stamp.isoformat(),
                                 is_opening_row=stamp.time() == dt.time(9, 30),
                                 source=row.get('source', 'futu'), adjustment='none')
                    payload = json.dumps(value, sort_keys=True)
                    digest = hashlib.sha256(payload.encode()).hexdigest()
                    old = self.db.execute('SELECT digest FROM bars WHERE symbol=? AND '
                                          'provider_time=? ORDER BY id DESC LIMIT 1',
                                          (symbol, stamp.isoformat())).fetchone()
                    if old and old[0] == digest:
                        continue
                    self.db.execute('INSERT INTO bars VALUES(NULL,?,?,?,?,?,?)',
                                    (symbol, stamp.isoformat(), now.isoformat(), digest, payload, raw))
                    added += 1
                except (KeyError, ValueError, TypeError) as exc:
                    errors.append({'time': str(row.get('time_key')), 'error': str(exc)})
        return {'added_versions': added, 'unfinished': unfinished, 'errors': errors}

    def close(self) -> None:
        self.db.close()


def read_for_strategy(database: Path, status_path: Path, symbol: str, *,
                      now: dt.datetime, count: int = 20) -> dict:
    """Fail closed on dead collectors, stale/suspended quotes, gaps or unavailable versions.

    Futu provider labels are deliberately not relabelled as TDX 240-bar timestamps.
    Revisions/backfills can only be observed at/after their local available_at.
    """
    if now.tzinfo is None or count < 1:
        raise ValueError('An aware clock and positive count are required')
    now = now.astimezone(TZ)
    status = json.loads(status_path.read_text(encoding='utf-8'))
    age = (now - dt.datetime.fromisoformat(status['heartbeat'])).total_seconds()
    if not 0 <= age <= status['heartbeat_max_age_seconds'] or \
            status['status'] != 'running' or status['phase'] != 'trading' or \
            phase(now) != 'trading' or status['as_of'] != str(now.date()):
        raise ValueError('Realtime collector is not healthy in the current trading session')
    if symbol not in status['symbols'] or symbol in status.get('symbol_errors', {}):
        raise ValueError('Symbol unavailable or has an unresolved feed error')
    stamp = now.isoformat()
    with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as db:
        row = db.execute('SELECT payload FROM quotes WHERE symbol=? AND received_at<=? '
                         'ORDER BY id DESC LIMIT 1', (symbol, stamp)).fetchone()
        if not row:
            raise ValueError('No quote available')
        quote = json.loads(row[0])
        quote_age = (now - dt.datetime.fromisoformat(quote['provider_time'])).total_seconds()
        if not 0 <= quote_age <= status['quote_max_age_seconds'] or quote['suspension']:
            raise ValueError('Quote is stale, future-dated or suspended')
        required = [t.isoformat() for t in minute_grid(now.date())
                    if t.time() != dt.time(9, 30)
                    and t + dt.timedelta(seconds=status['confirmation_seconds']) <= now][-count:]
        if len(required) < count:
            raise ValueError('Insufficient completed minutes today')
        rows = db.execute('SELECT b.payload,b.available_at FROM bars b JOIN '
                          '(SELECT provider_time,MAX(id) id FROM bars WHERE symbol=? '
                          'AND available_at<=? GROUP BY provider_time) x ON b.id=x.id '
                          'WHERE b.provider_time>=? ORDER BY b.provider_time',
                          (symbol, stamp, required[0])).fetchall()
    found = {json.loads(row[0])['provider_time']: {**json.loads(row[0]), 'available_at': row[1]}
             for row in rows}
    if any(t not in found for t in required):
        raise ValueError('Missing completed minute; no fill-forward or silent substitution')
    if len({found[t]['source'] for t in required}) != 1:
        raise ValueError('Mixed minute sources; wait for a complete provider window')
    return {'symbol': symbol, 'as_of': stamp, 'quote': quote,
            'bars': [found[t] for t in required], 'auto_trade': False}
