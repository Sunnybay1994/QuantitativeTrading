import datetime as dt
import json
from concurrent.futures import Future

import pytest

from quant.data.realtime_inputs import TZ
from quant.data.realtime_store import FeedStore, atomic_json, raw_packet, read_for_strategy
from quant.data.recent_minutes import normalize


def bar(label='09:31:00', source='akshare_sina'):
    return dict(code='SZ.000001', time_key='2026-09-18 ' + label, open=10., high=11.,
                low=9., close=10., volume=100., turnover=None, source=source)


def at(label):
    return dt.datetime.fromisoformat('2026-09-18T' + label).replace(tzinfo=TZ)


def quote(label='09:33:05', source='tushare_sina'):
    return dict(code='SZ.000001', data_date='2026-09-18', data_time=label,
                last_price=10, volume=100, turnover=1000, source=source)


def test_recent_keeps_missing_amount_and_full_returned_window():
    rows = [bar(), bar('09:32:00'), bar('09:30:00'), bar('12:01:00')]
    frame, rejected = normalize(rows, '000001.SZ', 'akshare_sina', dt.date(2026, 9, 18))
    assert frame.height == 2 and rejected == 1
    assert frame['amount'].null_count() == 2
    assert frame['bar_start'][0] == at('09:30:00')


def test_recent_rejects_invalid_ohlc_and_ignores_future():
    wrong = {**bar(), 'high': 1}
    future = {**bar(), 'time_key': '2026-09-21 09:31:00'}
    frame, rejected = normalize([wrong, future], '000001.SZ', 'akshare_sina', dt.date(2026, 9, 18))
    assert frame.is_empty() and rejected == 1


def test_raw_sources_are_immutable_and_separate(tmp_path):
    paths = [raw_packet(tmp_path, 'quote', [quote()], at('09:33:05'), source=s)
             for s in ('futu', 'tushare_sina', 'akshare_eastmoney')]
    assert len(set(paths)) == 3 and all(s in p for s, p in zip(
        ('futu', 'tushare_sina', 'akshare_eastmoney'), paths))


def test_stale_primary_cannot_replace_newer_fallback(tmp_path):
    store = FeedStore(tmp_path / 'market.sqlite')
    store.quotes([quote()], at('09:33:06'), 'public', ['000001.SZ'])
    store.quotes([quote('09:31:00', 'futu')], at('09:33:07'), 'primary', ['000001.SZ'])
    rows = store.db.execute('SELECT payload FROM quotes').fetchall()
    assert len(rows) == 1 and json.loads(rows[0][0])['source'] == 'tushare_sina'
    store.close()


def test_quote_fields_preserved_without_inventing_missing_book(tmp_path):
    store = FeedStore(tmp_path/'market.sqlite')
    try:
        q = dict(quote(), prev_close=9.8, bid=9.99, ask=10.01)
        assert store.quotes([q], at('09:33:06'), 'raw', ['000001.SZ']) == []
        saved = json.loads(store.db.execute('SELECT payload FROM quotes ORDER BY id DESC').fetchone()[0])
        assert [saved[k] for k in ('prev_close','bid','ask')] == [9.8, 9.99, 10.01]
        q.update(prev_close=None, bid=0, ask=float('nan'))
        assert store.quotes([q], at('09:33:07'), 'raw2', ['000001.SZ']) == []
        saved = json.loads(store.db.execute('SELECT payload FROM quotes ORDER BY id DESC').fetchone()[0])
        assert all(saved[k] is None for k in ('prev_close','bid','ask'))
    finally:
        store.close()


def test_reader_accepts_fallback_but_rejects_mixed_minute_sources(tmp_path):
    database, status = tmp_path / 'market.sqlite', tmp_path / 'status.json'
    store = FeedStore(database)
    rows = [{**bar(label, source), 'turnover': 1000}
            for label, source in [('09:31:00', 'futu'), ('09:32:00', 'akshare_eastmoney')]]
    store.bars(rows, '000001.SZ', at('09:33:05'), 'r', 63)
    store.quotes([quote()], at('09:33:05'), 'r', ['000001.SZ'])
    atomic_json(status, dict(status='running', phase='trading', as_of='2026-09-18',
        heartbeat=at('09:33:05').isoformat(), heartbeat_max_age_seconds=30, quote_max_age_seconds=30,
        symbols=['000001.SZ'], confirmation_seconds=63))
    with pytest.raises(ValueError, match='Mixed'):
        read_for_strategy(database, status, '000001.SZ', now=at('09:33:05'), count=2)
    rows[0]['source'] = 'akshare_eastmoney'
    store.bars(rows, '000001.SZ', at('09:33:05'), 'r', 63)
    result = read_for_strategy(database, status, '000001.SZ', now=at('09:33:05'), count=2)
    assert result['quote']['source'] == 'tushare_sina'
    assert all(b['source'] == 'akshare_eastmoney' for b in result['bars'])
    store.close()


def test_pending_fallback_does_not_block_heartbeat(tmp_path, monkeypatch):
    from quant.data.realtime_fallback import FallbackFeed
    feed = FallbackFeed(dict(data_root=str(tmp_path), confirmation_seconds=63, quote_max_age_seconds=30),
                        FeedStore(tmp_path / 'market.sqlite'))
    pending = []
    def submit(*args):
        future = Future()
        pending.append(future)
        return future
    monkeypatch.setattr(feed.pool, 'submit', submit)
    state = dict(symbol_errors={})
    feed.tick(['000001.SZ'], at('09:33:05'), state)
    assert len(pending) == 3
    feed.tick(['000001.SZ'], at('09:33:06'), state)
    assert len(pending) == 3 and len(state['fallback']['pending']) == 3
    for future in pending:
        future.cancel()
    feed.close()
    feed.store.close()


def test_request_deadline_terminates_worker():
    from quant.data.connectors.public_market import PublicMarket
    class Pipe:
        def send(self, args):
            pass
        def poll(self, timeout):
            return False
        def close(self):
            self.closed = True
    class Process:
        terminated = False
        def terminate(self):
            self.terminated = True
        def join(self, timeout):
            pass
    client = PublicMarket(timeout=0.01)
    process = Process()
    client.process, client.pipe = process, Pipe()
    with pytest.raises(TimeoutError):
        client.fetch('quotes', ['000001.SZ'], 'tushare_sina')
    assert process.terminated and client.process is None


def test_collector_runs_fallback_while_primary_is_offline(tmp_path, monkeypatch):
    from quant.data import realtime, realtime_fallback, refresh
    elapsed, ticks, publications = [0.], [], []
    cfg = dict(auto_trade=False, public_fallback=True, output=str(tmp_path/'out'),
        database=str(tmp_path/'market.sqlite'), data_root=str(tmp_path), confirmation_seconds=63,
        quote_max_age_seconds=30, heartbeat_max_age_seconds=30, host='localhost', port=11111,
        quota_reserve=10, quote_poll_seconds=5, bar_poll_seconds=60)
    class Fallback:
        def __init__(self, *args):
            pass
        def tick(self, symbols, now, state, **kwargs):
            ticks.append(now)
        def close(self):
            pass
    def offline(*args):
        raise ConnectionError('offline')
    monkeypatch.setattr(realtime, 'load_config', lambda _: cfg)
    monkeypatch.setattr(realtime, 'watchlist', lambda *args, **kw: dict(symbols=['000001.SZ']))
    monkeypatch.setattr(refresh, 'latest_session', lambda **kw: at('10:00:00').date())
    monkeypatch.setattr(realtime, 'FutuRealtime', offline)
    monkeypatch.setattr(realtime_fallback, 'FallbackFeed', Fallback)
    monkeypatch.setattr(realtime, 'atomic_json', lambda p, s: publications.append(dict(s)))
    monkeypatch.setattr(realtime.time, 'monotonic', lambda: elapsed[0])
    monkeypatch.setattr(realtime.time, 'sleep', lambda seconds: elapsed.__setitem__(0, elapsed[0]+seconds))
    result = realtime.run(tmp_path/'cfg', max_seconds=5,
                          now_fn=lambda: at('10:00:00')+dt.timedelta(seconds=elapsed[0]))
    assert len(ticks) >= 5 and result['history_requests'] == 0
    assert any(p.get('status') == 'running' and p.get('primary_available') is False for p in publications)


def test_history_plan_reuses_old_plans_and_lists_beijing(tmp_path, monkeypatch):
    from quant.data import minute_history
    config = tmp_path/'config.toml'
    config.write_text(f'auto_trade=false\ndata_root="{tmp_path.as_posix()}"\n'
        f'output="{(tmp_path/"out").as_posix()}"\nrecent_output="{(tmp_path/"recent").as_posix()}"\n'
        'start="2023-01-01"\nend="2026-09-18"\n')
    path = tmp_path/'clean/futu_minute/old_plan/symbol=00700.HK/year=2026/data.parquet'
    path.parent.mkdir(parents=True)
    path.touch()
    monkeypatch.setattr(minute_history, 'history_universe', lambda *args: [
        dict(symbol='000001.SZ', list_date='19910403'),
        dict(symbol='920001.BJ', list_date='20200101'),
        dict(symbol='00700.HK', list_date='20000101',consumer='fixture-hk-history',consumer_priority=0)])
    result = minute_history.run(config, check_only=True)
    plan = json.loads((tmp_path/'out/plan.json').read_text())
    assert result['unsupported_symbols'] == ['000001.SZ', '920001.BJ']
    assert plan['queue'][0]['symbol'] == '00700.HK'
    assert plan['queue'][0]['years'] == [2025,2024,2023]
    assert plan['queue'][0]['consumer'] == 'fixture-hk-history'


def test_history_earliest_mode_preserves_oldest_first(tmp_path, monkeypatch):
    from quant.data import minute_history
    config = tmp_path/'config.toml'
    config.write_text(f'auto_trade=false\nearliest_available=true\ndata_root="{tmp_path.as_posix()}"\n'
        f'output="{(tmp_path/"out").as_posix()}"\nrecent_output="{(tmp_path/"recent").as_posix()}"\n'
        'start="1990-01-01"\nend="2026-09-18"\n')
    monkeypatch.setattr(minute_history, 'history_universe', lambda *args: [dict(
        symbol='00700.HK',list_date='20000101',consumer='fixture-hk-history',consumer_priority=0)])
    atomic_json(tmp_path/'out/earliest_bounds.json', {'00700.HK': dict(
        requested_start='2000-01-01', requested_end='2026-09-18', first_date='2018-09-17')})
    minute_history.run(config, check_only=True)
    plan = json.loads((tmp_path/'out/plan.json').read_text())
    assert plan['queue'][0]['symbol'] == '00700.HK'
    assert plan['queue'][0]['years'] == list(range(2018, 2027))
    assert plan['queue'][0]['start'] == '2018-09-17'


def test_earliest_probe_uses_actual_response_and_cache(tmp_path, monkeypatch):
    import pandas as pd
    from quant.data import minute_history
    calls = []
    def page(*args):
        calls.append(args)
        return pd.DataFrame(dict(code=['SZ.000001'], time_key=['2018-09-17 09:30:00'])), b'next'
    monkeypatch.setattr(minute_history, 'history_page', page)
    monkeypatch.setattr(minute_history.time, 'sleep', lambda _: None)
    cache = {}
    for _ in range(2):
        assert minute_history.earliest_available(None, '000001.SZ', '1990-01-01', '2026-09-18', tmp_path, cache) == '2018-09-17'
    assert len(calls) == 1
    assert cache['000001.SZ']['has_more'] is True
    assert list((tmp_path/'raw/futu/earliest_bounds').rglob('*.parquet'))


def test_charged_history_continues_past_empty_year_without_new_quota(tmp_path, monkeypatch):
    from quant.data import minute_history
    config = tmp_path/'config.toml'
    config.write_text(f'auto_trade=false\nearliest_available=true\ndata_root="{tmp_path.as_posix()}"\n'
        f'output="{(tmp_path/"out").as_posix()}"\nrecent_output="{(tmp_path/"recent").as_posix()}"\n'
        'start="1990-01-01"\nend="2020-12-31"\nquota_reserve=5\nmax_new_symbols=5\nmax_seconds=3600\n')
    class Client:
        context = None
        def close(self):
            pass
    monkeypatch.setattr(minute_history, 'FutuRealtime', Client)
    monkeypatch.setattr(minute_history, 'history_universe', lambda *args: [dict(
        symbol='00700.HK',list_date='20000101',consumer='fixture-hk-history',consumer_priority=0)])
    monkeypatch.setattr(minute_history, 'history_quota', lambda _: (95, 5, {'00700.HK'}))
    monkeypatch.setattr(minute_history, 'earliest_available', lambda *args: '2018-09-17')
    requested = []
    def download(context, symbol, begin, finish, raw, clean):
        requested.append(begin)
        return dict(symbol=symbol, empty=begin.startswith('2019'), rows=0 if begin.startswith('2019') else 241)
    monkeypatch.setattr(minute_history, 'download_year', download)
    result = minute_history.run(config)
    assert requested == ['2018-09-17', '2019-01-01', '2020-01-01']
    assert result['newly_charged_attempts'] == 0
    assert '2019' in json.loads((tmp_path/'out/progress.json').read_text())['00700.HK']['empty_years']
