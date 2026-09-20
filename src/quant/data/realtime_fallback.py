"""Nonblocking public quote/minute recovery while OpenD reconnects."""

import datetime as dt
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from quant.data.connectors.public_market import PublicMarket
from quant.data.realtime_inputs import TZ, minute_grid
from quant.data.realtime_store import raw_packet


class FallbackFeed:
    def __init__(self, settings, store):
        self.settings, self.store = settings, store
        self.pool = ThreadPoolExecutor(max_workers=3)
        self.clients = {key: PublicMarket() for key in ('tushare', 'akquote', 'akbar')}
        self.pending, self.due, self.errors = {}, {}, {}
        self.accepted = 0

    def tick(self, symbols, now, state, *, probe=False):
        tick = time.monotonic()
        for key, (future, requested, source) in list(self.pending.items()):
            if not future.done():
                continue
            del self.pending[key]
            try:
                rows = future.result()
                if not rows:
                    raise ValueError('Empty fallback response')
                received = dt.datetime.now(TZ)
                kind = 'k1m' if key == 'akbar' else 'quote'
                raw = raw_packet(Path(self.settings['data_root']), kind, rows, received, source=source)
                if kind == 'quote':
                    rows = [r for r in rows if probe or 0 <= (received - dt.datetime.fromisoformat(
                        r['data_date'] + 'T' + r['data_time']).replace(tzinfo=TZ)).total_seconds()
                        <= self.settings['quote_max_age_seconds']]
                    if not rows:
                        raise ValueError('Fallback quote is stale')
                    errors = self.store.quotes(rows, received, raw, requested)
                else:
                    if not any(str(r.get('time_key', '')).startswith(str(received.date())) for r in rows):
                        raise ValueError('Fallback has no current-session minute bars')
                    result = self.store.bars(rows, requested[0], received, raw,
                        self.settings['confirmation_seconds'])
                    errors = result['errors']
                    if not errors and rows:
                        state['symbol_errors'].pop(requested[0], None)
                if errors:
                    raise ValueError('Fallback response failed validation')
                self.accepted += len(rows)
                self.errors.pop(key, None)
            except Exception as exc:
                self.errors[key] = type(exc).__name__ + ': ' + str(exc)
                self.due[key] = tick + 60
        missing_quotes, missing_bars = [], []
        required = [t for t in minute_grid(now.date()) if t.time() != dt.time(9, 30)
                    and t + dt.timedelta(seconds=self.settings['confirmation_seconds']) <= now]
        for symbol in symbols:
            row = self.store.db.execute('SELECT provider_time FROM quotes WHERE symbol=? '
                'ORDER BY id DESC LIMIT 1', (symbol,)).fetchone()
            if not row or not 0 <= (now - dt.datetime.fromisoformat(row[0])).total_seconds() <= 20:
                missing_quotes.append(symbol)
            if required:
                found = {r[0] for r in self.store.db.execute('SELECT DISTINCT provider_time FROM bars '
                    'WHERE symbol=? AND provider_time>=?', (symbol, required[0].isoformat()))}
                if any(t.isoformat() not in found for t in required):
                    missing_bars.append(symbol)
        jobs = [('tushare', missing_quotes, 'tushare_sina', 'quotes'),
                ('akquote', missing_quotes, 'akshare_eastmoney', 'quotes'),
                ('akbar', missing_bars, 'akshare_eastmoney', 'bars')]
        for key, missing, source, operation in jobs:
            if not missing or key in self.pending or tick < self.due.get(key, 0):
                continue
            if key != 'tushare':
                symbol = min(missing, key=lambda s: self.due.get((key, s), 0))
                if tick < self.due.get((key, symbol), 0):
                    continue
                missing = [symbol]
                self.due[key, symbol] = tick + (60 if key == 'akbar' else 5)
            self.pending[key] = (self.pool.submit(self.clients[key].fetch, operation, missing, source), missing, source)
            self.due[key] = tick + (5 if key == 'tushare' else 0.2)
        state['fallback'] = dict(accepted_rows=self.accepted, errors=dict(self.errors),
            pending=list(self.pending), missing_quotes=missing_quotes, missing_bars=missing_bars)

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)
        for client in self.clients.values():
            client.close()
