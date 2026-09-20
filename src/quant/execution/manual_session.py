"""Durable rehearsal orders and user-reported fills; never submits broker orders."""
from contextlib import contextmanager
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import uuid

from quant.execution.manual_fills import import_events
from quant.execution.manual_reply_protocol import parse_reply

TZ = dt.timezone(dt.timedelta(hours=8))
TERMINAL = {'FILLED', 'CANCELLED', 'NOT_SUBMITTED', 'EXPIRED_UNSENT', 'SUPERSEDED'}


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def stamp(value):
    result = dt.datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(result, dt.datetime) or result.tzinfo is None:
        raise ValueError('Require timezone-aware timestamp')
    return result.astimezone(TZ)


class ManualSession:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                state TEXT NOT NULL, broker TEXT, submitted_qty INTEGER, reminded INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS inbox(id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                status TEXT NOT NULL, result TEXT);
            CREATE TABLE IF NOT EXISTS fills(id TEXT PRIMARY KEY, order_id TEXT NOT NULL,
                event TEXT NOT NULL, fee_pending INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY, text TEXT NOT NULL,
                order_id TEXT, status TEXT NOT NULL DEFAULT 'queued', provider_id TEXT,
                error TEXT);
            CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
        ''')

        columns = {r[1] for r in self.db.execute('PRAGMA table_info(orders)')}
        if 'submitted_price' not in columns:
            self.db.execute('ALTER TABLE orders ADD COLUMN submitted_price REAL')

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def meta(self, key):
        row = self.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        if row is None:
            raise ValueError('Session is not initialized')
        return json.loads(row[0])

    def initialize(self, *, opening: dict, sessions: list[str], account_id: str,
                   sender_id: str, chat_id: str, fee_reserve: float = 30.):
        """Initialize an isolated rehearsal, never assume user's real cash or positions."""
        if not all(isinstance(x, str) and x.strip() for x in (account_id, sender_id, chat_id)):
            raise ValueError('Require explicit account, sender and chat bindings')
        days = [dt.date.fromisoformat(x) for x in sessions]
        if days != sorted(set(days)) or not days or days[-1] <= dt.date.fromisoformat(opening['date']):
            raise ValueError('Require ordered calendar with future session')
        if not math.isfinite(fee_reserve) or fee_reserve <= 0:
            raise ValueError('Require conservative pending fee reserve')
        if opening.get('imported_events') or opening.get('last_event_timestamp'):
            raise ValueError('Require a clean opening snapshot')
        opening, _ = import_events(state=opening, events=[], sessions=tuple(days))
        spec = dict(account_id=account_id, broker='银河证券', planned_capital=100000,
                    sender_id=sender_id, chat_id=chat_id, fee_reserve=fee_reserve,
                    mode='rehearsal', auto_trade=False, session_id=uuid.uuid4().hex)
        with self.transaction():
            if self.db.execute('SELECT 1 FROM meta').fetchone():
                raise ValueError('Preserve existing session; cannot reinitialize')
            for key, value in [('spec', spec), ('opening', opening), ('sessions', sessions)]:
                self.db.execute('INSERT INTO meta VALUES (?,?)', (key, dump(value)))

    def events(self):
        return sorted([json.loads(r[0]) for r in self.db.execute('SELECT event FROM fills')],
                      key=lambda e: (e['timestamp'], e['event_id']))

    def book(self):
        return import_events(state=self.meta('opening'), events=self.events(),
                             sessions=tuple(dt.date.fromisoformat(x) for x in self.meta('sessions')))[0]

    def _queue(self, identifier, text, order_id=None):
        self.db.execute('INSERT OR IGNORE INTO outbox(id,text,order_id) VALUES (?,?,?)',
                        (identifier, '【演练 · 不下真实单】'+text, order_id))

    def _order(self, identifier):
        row = self.db.execute('SELECT * FROM orders WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise ValueError('Unknown order ID')
        return dict(row), json.loads(row['payload'])

    def _filled(self, identifier):
        return sum(json.loads(r[0])['quantity'] for r in
                   self.db.execute('SELECT event FROM fills WHERE order_id=?', (identifier,)))

    def add_order(self, order: dict, *, now: dt.datetime):
        now = stamp(now)
        needed = {'order_id', 'version', 'account_id', 'strategy_version', 'symbol', 'side',
                  'quantity', 'limit_price', 'valid_from', 'valid_until', 'signal_at'}
        if not needed <= set(order) or set(order) - needed - {'supersedes_order_id'}:
            raise ValueError('Require exact order fields')
        if (not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', order['order_id'])
                or type(order['version']) is not int or order['version'] < 1
                or not re.fullmatch(r'\d{6}\.(SH|SZ)', order['symbol'])
                or order['side'] not in ('BUY', 'SELL')
                or type(order['quantity']) is not int or order['quantity'] <= 0
                or not order['strategy_version']):
            raise ValueError('Invalid order identity, symbol, direction or quantity')
        # This release is stock T+1 rehearsal only. Do not apply stock rules to ETF T+0.
        if not (order['symbol'].startswith('00') and order['symbol'].endswith('.SZ')
                or order['symbol'].startswith('60') and order['symbol'].endswith('.SH')):
            raise ValueError('First release supports SH/SZ main-board stock rehearsal only')
        price = float(order['limit_price'])
        begin, end, signal = (stamp(order[k]) for k in ('valid_from', 'valid_until', 'signal_at'))
        if (not math.isfinite(price) or price <= 0 or signal > now or signal > begin
                or begin >= end or end <= now or begin.date() != end.date()
                or str(begin.date()) not in self.meta('sessions')):
            raise ValueError('Invalid price, signal time or execution window')
        if order['side'] == 'BUY' and order['quantity'] % 100:
            raise ValueError('Stock rehearsal buys require 100-share lots')
        spec = self.meta('spec')
        if order['account_id'] != spec['account_id']:
            raise ValueError('Wrong account')
        with self.transaction():
            existing = self.db.execute('SELECT payload FROM orders WHERE id=?', (order['order_id'],)).fetchone()
            if existing:
                if json.loads(existing[0]) != order:
                    raise ValueError('Conflicting existing order')
                return 'duplicate'
            if self.db.execute("SELECT 1 FROM inbox WHERE status IN ('pending','review')").fetchone():
                raise ValueError('Resolve pending or conflicting receipts before new proposals')
            previous = order.get('supersedes_order_id')
            if previous:
                prior, old = self._order(previous)
                if (prior['state'] not in ('NOT_SUBMITTED', 'CANCELLED', 'EXPIRED_UNSENT')
                        or old['symbol'] != order['symbol'] or old['side'] != order['side']
                        or order['version'] <= old['version']):
                    raise ValueError('Replacement requires known terminal state and matching identity')
            active = [dict(r) for r in self.db.execute('SELECT * FROM orders') if r['state'] not in TERMINAL]
            if any(json.loads(r['payload'])['symbol'] == order['symbol'] for r in active):
                raise ValueError('Resolve existing same-symbol proposal or working order')
            book = self.book()
            pending_fees = self.db.execute('SELECT count(DISTINCT order_id) FROM fills WHERE fee_pending=1').fetchone()[0]
            reserved_cash = pending_fees * spec['fee_reserve']
            for row in active:
                other = json.loads(row['payload'])
                if other['side'] == 'BUY':
                    reserved_cash += (other['quantity']-self._filled(row['id'])) * max(float(other['limit_price']), row['submitted_price'] or 0) + spec['fee_reserve']
            if order['side'] == 'BUY' and price*order['quantity']+spec['fee_reserve'] > book['cash']-reserved_cash:
                raise ValueError('Insufficient cash after working orders and pending fees')
            held = book['holdings'].get(order['symbol'], {}).get('quantity', 0)
            unavailable = sum(x['quantity'] for x in book['restricted_shares']
                              if x['symbol'] == order['symbol'] and x['list_date'] > str(begin.date()))
            if order['side'] == 'SELL' and order['quantity'] > held-unavailable:
                raise ValueError('Insufficient sellable T+1 shares')
            if previous:
                self.db.execute("UPDATE orders SET state='SUPERSEDED' WHERE id=?", (previous,))
            self.db.execute('INSERT INTO orders(id,payload,state) VALUES (?,?,?)',
                            (order['order_id'], dump(order), 'PLANNED'))
            self._queue('order:'+order['order_id'],
                        f"{order['order_id']} v{order['version']} {order['symbol']} {order['side']} "
                        f"{order['quantity']}股 限价{price}；窗口{begin.isoformat()}至{end.isoformat()}。"
                        '请用委托/成交/未操作固定格式回复。', order['order_id'])
        return 'created'

    def receive(self, envelope: dict):
        required = {'message_id', 'sender_id', 'chat_id', 'text'}
        if not required <= set(envelope) or any(not isinstance(envelope[k], str) or not envelope[k] for k in required):
            raise ValueError('Require authenticated message envelope')
        spec = self.meta('spec')
        # Untrusted senders never reach the account inbox or receive account replies.
        if (envelope['sender_id'], envelope['chat_id']) != (spec['sender_id'], spec['chat_id']):
            raise ValueError('Sender/chat is not authorized')
        payload = {k: envelope[k] for k in sorted(required)}
        with self.transaction():
            existing = self.db.execute('SELECT payload,status,result FROM inbox WHERE id=?',
                                       (payload['message_id'],)).fetchone()
            if existing:
                if json.loads(existing['payload']) != payload:
                    self.db.execute('INSERT INTO audit(payload) VALUES (?)',
                                    (dump({'reason': 'message_id_conflict', 'message': payload}),))
                    self.db.execute("UPDATE inbox SET status='review' WHERE id=?", (payload['message_id'],))
                    return {'status': 'review', 'reason': 'message_id_conflict'}
                return {'status': existing['status'], 'duplicate': True}
            self.db.execute('INSERT INTO inbox(id,payload,status) VALUES (?,?,?)',
                            (payload['message_id'], dump(payload), 'pending'))
        return {'status': 'pending'}

    def process(self, *, now: dt.datetime):
        now = stamp(now)
        results = []
        for message in list(self.db.execute("SELECT id FROM inbox WHERE status='pending' ORDER BY rowid")):
            with self.transaction():
                item = self.db.execute("SELECT * FROM inbox WHERE id=? AND status='pending'", (message['id'],)).fetchone()
                if item is None:
                    continue
                self.db.execute('SAVEPOINT apply_reply')
                try:
                    reply = parse_reply(json.loads(item['payload'])['text'])
                    result = self._apply(reply, now)
                    self.book()  # Rebuild all fills by execution time; rollback contradictory facts.
                    self.db.execute('RELEASE apply_reply')
                    status = 'processed'
                except (ValueError, KeyError, TypeError) as exc:
                    self.db.execute('ROLLBACK TO apply_reply')
                    self.db.execute('RELEASE apply_reply')
                    result, status = {'reason': str(exc), 'action': '请核对原回报；未更改持仓，勿重复下单。'}, 'review'
                self.db.execute('UPDATE inbox SET status=?,result=? WHERE id=?',
                                (status, dump(result), item['id']))
                self._queue('reply:'+item['id'], dump(result))
                results.append({'message_id': item['id'], 'status': status, **result})
        return results

    def _apply(self, reply, now):
        row, order = self._order(reply['order_id'])
        if reply['version'] != order['version']:
            raise ValueError('Order version mismatch')
        kind, quantity = reply['kind'], self._filled(row['id'])
        state = row['state']
        if kind in ('SUBMITTED', 'FILL', 'CANCELLED'):
            day = stamp(order['valid_from']).date()
            when = dt.datetime.combine(day, dt.time.fromisoformat(reply['execution_time']), TZ)
            if when > now or when < stamp(order['signal_at']):
                raise ValueError('Execution time is future or precedes signal')
        if kind == 'NOT_SUBMITTED':
            if quantity or row['broker'] or state in ('SUPERSEDED', 'CANCELLED'):
                raise ValueError('Cannot mark a working or filled order as never submitted')
            state = 'NOT_SUBMITTED'
            action = '已记录未操作；原建议停止。需按当前行情重新检查后另发版本，不自动补买。'
        elif kind == 'QUERY':
            if state in TERMINAL:
                raise ValueError('Conflicting query on terminal order')
            if row['broker'] and row['broker'] != reply['broker_order_id']:
                raise ValueError('Broker order mismatch')
            self.db.execute('UPDATE orders SET broker=? WHERE id=?', (reply['broker_order_id'], row['id']))
            state, action = 'AWAITING_CONFIRMATION', '请查询券商成交及在途数量；未确认前保留预留，不重复委托。'
        elif kind == 'SUBMITTED':
            if row['submitted_qty'] is not None and (row['submitted_qty'] != reply['quantity'] or row['submitted_price'] != float(reply['price'])):
                raise ValueError('Conflicting submitted quantity or price')
            if row['broker'] == reply['broker_order_id'] and row['submitted_qty'] == reply['quantity']:
                return {'order_id': row['id'], 'state': state, 'action': '该委托已登记，未重复记账。'}
            if state in TERMINAL or quantity > reply['quantity'] or reply['quantity'] > order['quantity']:
                raise ValueError('Invalid submitted quantity or terminal order')
            if row['broker'] and row['broker'] != reply['broker_order_id']:
                raise ValueError('Broker order mismatch')
            self.db.execute('UPDATE orders SET broker=?,submitted_qty=?,submitted_price=? WHERE id=?',
                            (reply['broker_order_id'], reply['quantity'], float(reply['price']), row['id']))
            state, action = 'SUBMITTED', '已登记委托，尚未增加持仓；成交后请报实际数量和价格。'
        elif kind == 'CANCELLED':
            if row['broker'] != reply['broker_order_id'] or row['submitted_qty'] is None:
                raise ValueError('Need matching submitted order before cancellation')
            if reply['quantity'] != row['submitted_qty']-quantity:
                raise ValueError('Cancelled remaining quantity differs; reconcile fills first')
            state, action = 'CANCELLED', '撤余单已记录；保留已成交数量，剩余目标须重新检查。'
        elif kind in ('FILL', 'FEE'):
            identifier = self.meta('spec')['account_id']+':'+str(stamp(order['valid_from']).date())+':'+reply['broker_trade_id']
            found = self.db.execute('SELECT * FROM fills WHERE id=?', (identifier,)).fetchone()
            if kind == 'FEE':
                if found is None or found['order_id'] != row['id']:
                    raise ValueError('Unknown broker fill for fee confirmation')
                event = json.loads(found['event'])
                if not found['fee_pending'] and event['fee'] != float(reply['fee']):
                    raise ValueError('Final fee conflict; preserve evidence for correction')
                event['fee'] = float(reply['fee'])
                self.db.execute('UPDATE fills SET event=?,fee_pending=0 WHERE id=?', (dump(event), identifier))
                action = '费用已确认；按原成交时间重算账本。'
            else:
                event = dict(event_id=identifier, timestamp=when.isoformat(), symbol=order['symbol'],
                             kind=order['side'], quantity=reply['quantity'], price=float(reply['price']),
                             fee=float(reply['fee']) if reply['fee'] is not None else 0.)
                pending = reply['fee'] is None
                if found:
                    saved = json.loads(found['event'])
                    if found['order_id'] != row['id'] or any(event[k] != saved[k] for k in event if k != 'fee'):
                        raise ValueError('Conflicting broker trade ID')
                    if not pending and event['fee'] != saved['fee']:
                        raise ValueError('Use explicit fee confirmation')
                    return {'order_id': row['id'], 'state': state, 'action': '重复成交回报，未重复入账。'}
                if quantity+event['quantity'] > (row['submitted_qty'] or order['quantity']):
                    raise ValueError('Reported fills exceed quantity; reconcile external trade')
                self.db.execute('INSERT INTO fills VALUES (?,?,?,?)', (identifier, row['id'], dump(event), int(pending)))
                quantity += event['quantity']
                # Late reports are facts; invalidate any replacement suggestion until reconciliation.
                children = list(self.db.execute('SELECT * FROM orders'))
                for child in children:
                    if json.loads(child['payload']).get('supersedes_order_id') == row['id']:
                        self.db.execute("UPDATE orders SET state='AWAITING_CONFIRMATION' WHERE id=?", (child['id'],))
                        self.db.execute("UPDATE outbox SET status='cancelled' WHERE order_id=? AND status='queued'", (child['id'],))
                        self._queue('late:'+identifier+':'+child['id'], '补报成交改变持仓，请核对替代建议'+child['id']+'的券商在途单；勿重复下单。')
                deviation = not (stamp(order['valid_from']) <= when < stamp(order['valid_until'])) or (
                    event['price'] > float(order['limit_price']) if order['side'] == 'BUY'
                    else event['price'] < float(order['limit_price']))
                state = 'FILLED' if quantity == (row['submitted_qty'] or order['quantity']) else 'PARTIAL'
                action = '实际成交已暂记；费用待核。' if pending else '实际成交已记账。'
                if deviation:
                    action += ' 存在时点或限价偏差，已保留真实成交。'
        else:
            raise ValueError('Unsupported reply')
        self.db.execute('UPDATE orders SET state=? WHERE id=?', (state, row['id']))
        if state != 'PLANNED':
            self.db.execute("UPDATE outbox SET status='cancelled' WHERE order_id=? AND status='queued'", (row['id'],))
        return {'order_id': row['id'], 'state': state, 'filled_quantity': quantity, 'action': action}

    def tick(self, *, now: dt.datetime):
        now = stamp(now)
        with self.transaction():
            for row in list(self.db.execute('SELECT * FROM orders')):
                order = json.loads(row['payload'])
                if row['state'] in TERMINAL or now < stamp(order['valid_until']):
                    continue
                sent = self.db.execute("SELECT status FROM outbox WHERE id=?", ('order:'+row['id'],)).fetchone()
                if row['state'] == 'PLANNED' and sent['status'] == 'queued':
                    self.db.execute("UPDATE orders SET state='EXPIRED_UNSENT' WHERE id=?", (row['id'],))
                    self.db.execute("UPDATE outbox SET status='expired' WHERE id=?", ('order:'+row['id'],))
                else:
                    self.db.execute("UPDATE orders SET state='AWAITING_CONFIRMATION' WHERE id=?", (row['id'],))
                    if not row['reminded']:
                        self._queue('check:'+row['id'], row['id']+'窗口已结束：请确认未操作/已委托/部分成交/已成交；不要重复下单。')
                        self.db.execute('UPDATE orders SET reminded=1 WHERE id=?', (row['id'],))

    def dispatch(self, sender, *, now: dt.datetime):
        """Ambiguous sends remain uncertain across restart, never blindly retry."""
        self.tick(now=now)
        sent = []
        for row in list(self.db.execute("SELECT * FROM outbox WHERE status='queued' ORDER BY rowid")):
            with self.transaction():
                if row['order_id']:
                    state, order = self._order(row['order_id'])
                    if (state['state'] != 'PLANNED' or stamp(now) < stamp(order['valid_from'])
                            or self.db.execute("SELECT 1 FROM inbox WHERE status IN ('pending','review')").fetchone()):
                        continue
                claimed = self.db.execute("UPDATE outbox SET status='sending' WHERE id=? AND status='queued'", (row['id'],)).rowcount
                if not claimed:
                    continue
            try:
                receipt = sender(self.meta('spec')['chat_id'], row['text'],
                                 hashlib.sha256((self.meta('spec').get('session_id', self.meta('spec')['account_id'])+':'+row['id']).encode()).hexdigest()[:32])
                if receipt.get('provider_accepted') is not True or not receipt.get('message_id'):
                    raise ValueError('Provider did not confirm acceptance')
                status, provider, error = 'provider_accepted', receipt['message_id'], None
            except Exception as exc:
                status, provider, error = 'uncertain', None, type(exc).__name__
            with self.transaction():
                self.db.execute('UPDATE outbox SET status=?,provider_id=?,error=? WHERE id=?',
                                (status, provider, error, row['id']))
                if row['order_id']:
                    self.db.execute("UPDATE orders SET state='AWAITING_CONFIRMATION' WHERE id=? AND state='PLANNED'", (row['order_id'],))
            sent.append({'id': row['id'], 'status': status})
        return sent

    def snapshot(self):
        orders = []
        for row in self.db.execute('SELECT * FROM orders ORDER BY id'):
            order = json.loads(row['payload'])
            orders.append({**order, 'state': row['state'], 'broker_order_id': row['broker'],
                           'filled_quantity': self._filled(row['id'])})
        pending = self.db.execute('SELECT count(*) FROM fills WHERE fee_pending=1').fetchone()[0]
        return {'mode': 'rehearsal', 'auto_trade': False, 'broker': '银河证券', 'book': self.book(),
                'fee_pending_fills': pending, 'cash_and_nav_final': False,
                'note': '用户回报演练账本；费用可能待核，未与券商独立对账。', 'orders': orders,
                'inbox': [dict(r) for r in self.db.execute('SELECT id,status,result FROM inbox')],
                'outbox': [dict(r) for r in self.db.execute('SELECT id,status,error FROM outbox')]}

    def resolve_review(self, identifier: str, *, retry: bool, reason: str):
        """Explicit operator recovery. Preserve original text and decision history."""
        if not reason.strip():
            raise ValueError('Require a recovery reason')
        with self.transaction():
            row = self.db.execute("SELECT * FROM inbox WHERE id=? AND status='review'", (identifier,)).fetchone()
            if row is None:
                raise ValueError('Message is not awaiting review')
            self.db.execute('INSERT INTO audit(payload) VALUES (?)',
                            (dump({'message_id': identifier, 'previous': dict(row),
                                   'decision': 'retry' if retry else 'dismiss', 'reason': reason}),))
            self.db.execute('UPDATE inbox SET status=? WHERE id=?',
                            ('pending' if retry else 'dismissed', identifier))
