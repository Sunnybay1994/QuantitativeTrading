import datetime as dt
import json
from pathlib import Path

import pytest

from quant.data.realtime import single_writer
from quant.data.realtime_inputs import (
    TZ, fit_quota, k1m_refresh_seconds, minute_grid, next_k1m_batch, phase, watchlist,
)
from quant.data.realtime_store import FeedStore, atomic_json, raw_packet, read_for_strategy


def at(value):
    return dt.datetime.fromisoformat('2026-09-18T' + value).replace(tzinfo=TZ)


def bar(label='09:31:00', close=10):
    return dict(code='SH.510300', time_key='2026-09-18 ' + label, open=10,
                high=11, low=9, close=close, volume=100, turnover=1000)


def quote(label='09:32:05'):
    return dict(code='SH.510300', data_date='2026-09-18', data_time=label,
                last_price=10, volume=100, turnover=1000, suspension=False)


def state(now):
    return dict(status='running', phase='trading', heartbeat=now.isoformat(),
                as_of='2026-09-18', symbols=['510300.SH'], symbol_errors={},
                heartbeat_max_age_seconds=30, quote_max_age_seconds=30,
                confirmation_seconds=63)


@pytest.mark.parametrize('time,expected', [('09:19:59','before_start'),('09:20:00','preopen'),
    ('09:30:00','trading'),('11:30:00','settling'),('11:33:00','lunch'),
    ('13:00:00','trading'),('15:00:00','settling'),('15:05:00','closed')])
def test_session_boundaries(time, expected):
    assert phase(at(time)) == expected


def test_provider_grid_keeps_opening_but_excludes_lunch():
    grid = minute_grid(at('09:30:00').date())
    assert len(grid) == 241
    assert at('13:00:00') not in grid
    assert at('11:30:00') in grid and at('15:00:00') in grid


def test_unfinished_requires_new_fetch_and_revisions_are_pit(tmp_path):
    db, status = tmp_path/'feed.sqlite', tmp_path/'status.json'
    store = FeedStore(db)
    assert store.bars([bar()], '510300.SH', at('09:32:02'), 'raw-a', 63)['unfinished'] == 1
    assert store.db.execute('SELECT count(*) FROM bars').fetchone()[0] == 0
    assert store.bars([bar()], '510300.SH', at('09:32:04'), 'raw-b', 63)['added_versions'] == 1
    assert store.bars([bar()], '510300.SH', at('09:32:05'), 'raw-c', 63)['added_versions'] == 0
    store.quotes([quote()], at('09:32:05'), 'raw-q', ['510300.SH'])
    atomic_json(status, state(at('09:32:05')))
    assert read_for_strategy(db, status, '510300.SH', now=at('09:32:05'), count=1)['bars'][0]['close'] == 10
    store.bars([bar(close=11)], '510300.SH', at('09:32:10'), 'raw-d', 63)
    assert read_for_strategy(db, status, '510300.SH', now=at('09:32:05'), count=1)['bars'][0]['close'] == 10
    assert read_for_strategy(db, status, '510300.SH', now=at('09:32:11'), count=1)['bars'][0]['close'] == 11
    store.close()


@pytest.mark.parametrize('problem', ['stale_quote','suspended','dead','probe','gap','future_heartbeat'])
def test_strategy_rejects_unusable_feed(tmp_path, problem):
    db, path, now = tmp_path/'feed.sqlite', tmp_path/'status.json', at('09:33:05')
    store = FeedStore(db)
    rows = [bar(), bar('09:32:00')]
    if problem == 'gap':
        rows = rows[:1]
    store.bars(rows, '510300.SH', now, 'r', 63)
    q = quote('09:33:00' if problem != 'stale_quote' else '09:31:00')
    q['suspension'] = problem == 'suspended'
    store.quotes([q], now, 'q', ['510300.SH'])
    s = state(now)
    if problem == 'dead':
        s['heartbeat'] = at('09:31:00').isoformat()
    if problem == 'future_heartbeat':
        s['heartbeat'] = at('09:34:00').isoformat()
    if problem == 'probe':
        s['status'] = 'probe_complete'
    atomic_json(path, s)
    with pytest.raises(ValueError):
        read_for_strategy(db, path, '510300.SH', now=now, count=2)
    store.close()


def test_invalid_and_wrong_symbol_never_enter_clean(tmp_path):
    store = FeedStore(tmp_path/'feed.sqlite')
    malformed = bar(close=float('nan'))
    assert store.bars([malformed], '510300.SH', at('10:00:00'), 'r', 63)['errors']
    assert store.bars([bar()], '159915.SZ', at('10:00:00'), 'r', 63)['errors']
    assert store.quotes([quote('10:01:00')], at('10:00:00'), 'r', ['510300.SH'])
    assert store.db.execute('SELECT count(*) FROM bars').fetchone()[0] == 0
    store.close()


def test_raw_no_overwrite_and_lock_releases(tmp_path):
    a = raw_packet(tmp_path, 'quote', [quote()], at('09:32:05'))
    b = raw_packet(tmp_path, 'quote', [quote()], at('09:32:05'))
    assert a != b and Path(a).is_file() and Path(b).is_file()
    with single_writer(tmp_path/'writer.lock'):
        with pytest.raises(OSError):
            with single_writer(tmp_path/'writer.lock'):
                pass
    with single_writer(tmp_path/'writer.lock'):
        pass


def test_watch_prioritizes_held_and_today_orders_and_freezes_scope(tmp_path):
    folder = tmp_path/'2026-09-18'
    folder.mkdir()
    (folder/'positions.csv').write_text('symbol,quantity\n510300.SH,100\n511010.SH,0\n')
    (folder/'orders.csv').write_text('symbol,execution_date\n159915.SZ,2026-09-21\n518880.SH,2026-09-18\n')
    cfg = dict(account_roots=[str(tmp_path)], symbols=['600000.SH','600001.SH'], max_symbols=3)
    result = watchlist(cfg, dt.date(2026,9,21))
    assert result['symbols'] == ['159915.SZ','510300.SH','600000.SH']
    assert result['omitted_representatives'] == ['600001.SH']
    assert cfg['symbols'] == ['600000.SH','600001.SH']
    cfg['max_symbols'] = 1
    with pytest.raises(ValueError, match='Positions/orders'):
        watchlist(cfg, dt.date(2026,9,21))


def test_collector_offday_never_connects(tmp_path, monkeypatch):
    from quant.data import realtime
    from quant.data import refresh
    settings = dict(auto_trade=False, output=str(tmp_path/'out'), database=str(tmp_path/'db'),
        data_root=str(tmp_path), confirmation_seconds=63, quote_max_age_seconds=30,
        heartbeat_max_age_seconds=30)
    monkeypatch.setattr(realtime, 'load_config', lambda _: settings)
    monkeypatch.setattr(refresh, 'latest_session', lambda **_: dt.date(2000,1,1))
    monkeypatch.setattr(realtime, 'FutuRealtime', lambda *_: pytest.fail('No connection off-session'))
    result = realtime.run(tmp_path/'cfg')
    assert result['status'] == 'idle' and result['history_requests'] == 0
    assert json.loads((tmp_path/'out/status.json').read_text())['status'] == 'idle'


def test_collector_reconnects_and_recovers_without_history(tmp_path, monkeypatch):
    from quant.data import realtime, refresh
    elapsed, connections = [0.0], []
    def now():
        return at('10:00:00') + dt.timedelta(seconds=elapsed[0])
    cfg = dict(auto_trade=False, output=str(tmp_path/'out'), database=str(tmp_path/'feed.sqlite'),
        data_root=str(tmp_path), confirmation_seconds=63, quote_max_age_seconds=30,
        heartbeat_max_age_seconds=30, host='localhost', port=11111, quota_reserve=10,
        quote_poll_seconds=5, bar_poll_seconds=60)

    class Client:
        def __init__(self, *_):
            connections.append(self)
            self.closed = False

        def state(self):
            if len(connections) == 1:
                raise ConnectionError('disconnect')
            return {'timestamp': now().timestamp()}

        def subscribe_quotes(self, symbols, reserve):
            assert symbols == ['510300.SH'] and reserve == 10
            return {'remain': 89}

        def subscribe_k1m(self, symbols, reserve=None):
            assert symbols == ['510300.SH']
            return {'remain': 88}

        def unsubscribe_k1m(self, symbols):
            return {'remain': 89}

        def quota(self):
            return {'remain': 100}

        def quotes(self, symbols):
            return [quote(now().strftime('%H:%M:%S'))]

        def bars(self, symbol):
            return [bar('09:59:00'), bar('10:00:00')]

        def close(self):
            self.closed = True

    monkeypatch.setattr(realtime, 'load_config', lambda _: {**cfg, 'k1m_rotate_seconds': 65})
    monkeypatch.setattr(realtime, 'watchlist', lambda *_, **kw: {
        'symbols': ['510300.SH'], 'holdings': [], 'orders': []})
    monkeypatch.setattr(refresh, 'latest_session', lambda **_: now().date())
    monkeypatch.setattr(realtime, 'FutuRealtime', Client)
    monkeypatch.setattr(realtime.time, 'monotonic', lambda: elapsed[0])
    monkeypatch.setattr(realtime.time, 'sleep', lambda seconds: elapsed.__setitem__(0, elapsed[0]+seconds))
    result = realtime.run(tmp_path/'cfg', max_seconds=70, now_fn=now)
    assert result['reconnects'] == 1 and result['bar_requests'] == 1
    assert result['history_requests'] == 0 and all(c.closed for c in connections)
    assert result['status'] == 'stopped'
    store = FeedStore(tmp_path/'feed.sqlite')
    assert store.db.execute('SELECT count(*) FROM bars').fetchone()[0] == 2
    store.close()


def test_quota_quote_first_trims_only_representatives():
    selection = dict(symbols=['510300.SH', '159915.SZ', '600000.SH'],
                     holdings=['510300.SH'], orders=['159915.SZ'])
    # available=4 QUOTE slots → all 3 admitted, 1 leftover for K_1M
    fitted = fit_quota(selection, remaining=14, reserve=10)
    assert fitted['symbols'] == selection['symbols']
    assert fitted['quote_slots'] == 3 and fitted['k1m_slots'] == 1
    # available=2 exactly covers mandatory QUOTE; representative dropped; no K leftover
    fitted = fit_quota(selection, remaining=12, reserve=10)
    assert fitted['symbols'] == ['510300.SH', '159915.SZ']
    assert fitted['k1m_slots'] == 0
    with pytest.raises(ValueError, match='QUOTE'):
        fit_quota(selection, remaining=11, reserve=10)


def test_quota_allows_53_mandatory_quotes_on_100_tier():
    mandatory = [f'{i:06d}.SH' for i in range(53)]
    selection = dict(symbols=mandatory, holdings=mandatory[:40], orders=mandatory[40:])
    fitted = fit_quota(selection, remaining=100, reserve=10)
    assert fitted['symbols'] == mandatory
    assert fitted['quote_slots'] == 53 and fitted['k1m_slots'] == 37
    assert k1m_refresh_seconds(53, 37, 65) == 130
    assert k1m_refresh_seconds(53, 53, 65) is None


def test_k1m_batch_rotates_round_robin():
    symbols = [f'{i:06d}.SH' for i in range(5)]
    batch, cursor = next_k1m_batch(symbols, 3, 0)
    assert batch == ['000000.SH', '000001.SH', '000002.SH'] and cursor == 3
    batch, cursor = next_k1m_batch(symbols, 3, cursor)
    assert batch == ['000003.SH', '000004.SH', '000000.SH'] and cursor == 1
    assert next_k1m_batch(symbols, 5, 2)[0] == symbols
    assert next_k1m_batch(symbols, 0, 1) == ([], 1)


def test_stale_account_is_not_silently_treated_as_current(tmp_path):
    (tmp_path/'2026-09-17').mkdir()
    with pytest.raises(ValueError, match='Stale account'):
        watchlist(dict(account_roots=[str(tmp_path)],max_symbols=40), dt.date(2026,9,21),
                  previous_session=dt.date(2026,9,18))


def test_collector_rotates_k1m_on_leftover_slots(tmp_path, monkeypatch):
    from quant.data import realtime, refresh
    elapsed, events = [0.0], []

    def now():
        return at('10:00:00') + dt.timedelta(seconds=elapsed[0])

    cfg = dict(auto_trade=False, output=str(tmp_path / 'out'), database=str(tmp_path / 'feed.sqlite'),
               data_root=str(tmp_path), confirmation_seconds=63, quote_max_age_seconds=30,
               heartbeat_max_age_seconds=30, host='localhost', port=11111, quota_reserve=10,
               quote_poll_seconds=5, bar_poll_seconds=60, k1m_rotate_seconds=65)
    symbols = ['510300.SH', '159915.SZ', '518880.SH']

    class Client:
        def __init__(self, *_):
            self.k1m = set()

        def state(self):
            return {'timestamp': now().timestamp()}

        def quota(self):
            # available=5 → quote all 3, k1m_slots=2
            return {'remain': 15}

        def subscribe_quotes(self, chosen, reserve):
            assert chosen == symbols and reserve == 10
            events.append(('quote', list(chosen)))
            return {'remain': 12}

        def subscribe_k1m(self, batch, reserve=None):
            events.append(('sub_k', list(batch)))
            self.k1m.update(batch)
            return {'remain': 12 - len(self.k1m)}

        def unsubscribe_k1m(self, batch):
            events.append(('unsub_k', list(batch)))
            self.k1m.difference_update(batch)
            return {'remain': 12 - len(self.k1m)}

        def quotes(self, chosen):
            return [dict(code='SH.' + s.split('.')[0] if s.endswith('.SH') else 'SZ.' + s.split('.')[0],
                         data_date='2026-09-18', data_time=now().strftime('%H:%M:%S'),
                         last_price=10, volume=100, turnover=1000, suspension=False)
                    for s in chosen]

        def bars(self, symbol):
            assert symbol in self.k1m
            return [bar('09:59:00'), bar('10:00:00')]

        def close(self):
            pass

    monkeypatch.setattr(realtime, 'load_config', lambda _: cfg)
    monkeypatch.setattr(realtime, 'watchlist', lambda *_, **kw: {
        'symbols': symbols, 'holdings': symbols[:2], 'orders': []})
    monkeypatch.setattr(refresh, 'latest_session', lambda **_: now().date())
    monkeypatch.setattr(realtime, 'FutuRealtime', Client)
    monkeypatch.setattr(realtime.time, 'monotonic', lambda: elapsed[0])
    monkeypatch.setattr(realtime.time, 'sleep', lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds))
    result = realtime.run(tmp_path / 'cfg', max_seconds=70, now_fn=now)
    assert events[0] == ('quote', symbols)
    assert events[1][0] == 'sub_k' and len(events[1][1]) == 2
    assert any(kind == 'unsub_k' for kind, _ in events)
    assert result.get('k1m_rotations', 0) >= 1
    assert result['k1m_slots'] == 2
    assert result['status'] == 'stopped'
