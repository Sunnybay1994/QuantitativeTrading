"""BaoStock wire-request budget shared by all project processes.

https://www.baostock.com/blacklist: <=50,000 requests/day, no concurrent
connections. Use 40,000 per rolling 24h and at least one second per send.
The exclusive session lock must be held while using this ledger.
"""
import sqlite3
import time
import os
import errno
from contextlib import contextmanager
from pathlib import Path

# Independent of cwd/checkouts. Never fall back to a private per-project ledger.
ROOT = (Path(os.environ.get('PROGRAMDATA', 'C:/ProgramData')) / 'QuantitativeTrading/baostock_access'
        if os.name == 'nt' else Path('/var/lib/quantitative-trading/baostock_access'))


class BaoStockAccessPaused(RuntimeError):
    pass


@contextmanager
def session_slot(root=None, *, timeout=60.0):
    """Wait up to timeout for the shared connection; release on process exit too."""
    from quant.data.realtime import single_writer
    root = ROOT if root is None else root
    deadline = time.monotonic() + timeout
    while True:
        lock = single_writer(root / 'session.lock')
        try:
            lock.__enter__()
        except OSError as exc:
            # Retry only lock contention, never hide permissions/disk failures.
            contention = (exc.errno == errno.EACCES and getattr(exc, 'winerror', None) in (None, 33, 36)
                          if os.name == 'nt' else exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK))
            if not contention:
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BaoStockAccessPaused('BaoStock connection busy: wait timed out; retry later') from exc
            time.sleep(min(0.2, remaining))
        else:
            break
    try:
        yield
    finally:
        lock.__exit__(None, None, None)


class AccessBudget:
    def __init__(self, root=None, *, limit=40000, clock=time.time, sleep=time.sleep):
        root = ROOT if root is None else root
        root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(root / 'requests.sqlite')
        self.db.execute('CREATE TABLE IF NOT EXISTS requests (at REAL NOT NULL)')
        self.db.execute('CREATE INDEX IF NOT EXISTS request_time ON requests(at)')
        self.db.execute('CREATE TABLE IF NOT EXISTS control (id INTEGER PRIMARY KEY, blocked INTEGER)')
        self.db.execute('CREATE TABLE IF NOT EXISTS sessions (at REAL, pid INTEGER, event TEXT)')
        self.db.commit()
        self.limit, self.clock, self.sleep = limit, clock, sleep
        self.error = None

    def check(self):
        row = self.db.execute('SELECT blocked FROM control WHERE id=1').fetchone()
        if row and row[0]:
            raise BaoStockAccessPaused('BaoStock blacklist: awaiting verified release; no network requests allowed')
        count = self.db.execute('SELECT COUNT(*) FROM requests WHERE at>?', (self.clock()-86400,)).fetchone()[0]
        if count >= self.limit:
            raise BaoStockAccessPaused('BaoStock rolling 24h request budget exhausted')

    def reserve(self):
        try:
            self.check()
            last = self.db.execute('SELECT MAX(at) FROM requests').fetchone()[0]
            if last is not None:
                self.sleep(max(0, last + 1.0 - self.clock()))
            self.check()
            now = self.clock()
            self.db.execute('DELETE FROM requests WHERE at<=?', (now-86400,))
            self.db.execute('INSERT INTO requests VALUES (?)', (now,))
            self.db.commit()  # Charge before send: failed requests and process crashes count.
        except Exception as exc:
            self.error = exc
            raise

    def block(self):
        self.db.execute('INSERT OR REPLACE INTO control VALUES (1,1)')
        self.db.commit()

    def begin_session(self):
        self.check()
        previous = self.db.execute("SELECT at,event FROM sessions WHERE event IN ('closed','failed') ORDER BY at DESC LIMIT 1").fetchone()
        if previous:
            delay = (60 if previous[1] == 'failed' else 5) - (self.clock()-previous[0])
            if delay > 0:
                # Hold the source slot while cooling down: callers must not
                # turn a source-wide delay into failures for successive symbols.
                self.sleep(min(delay, 60))
                self.check()
        self.session_event('opening')

    def session_event(self, event):
        self.db.execute('INSERT INTO sessions VALUES (?,?,?)', (self.clock(), os.getpid(), event))
        self.db.commit()


class BudgetSocket:
    def __init__(self, socket, budget):
        self.socket, self.budget = socket, budget

    def send(self, *args, **kwargs):
        self.budget.reserve()
        return self.socket.send(*args, **kwargs)

    def sendall(self, *args, **kwargs):
        self.budget.reserve()
        return self.socket.sendall(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.socket, name)
