"""Trading-day subscribed Futu feed. QUOTE-first; rotating unadjusted K_1M on leftover quota."""

import argparse
import contextlib
import datetime as dt
import json
import os
import time
from pathlib import Path

from quant.data.connectors.futu_realtime import FutuRealtime
from quant.data.realtime_inputs import (
    TZ, fit_quota, k1m_refresh_seconds, load_config, next_k1m_batch, phase, watchlist,
)
from quant.data.realtime_store import FeedStore, atomic_json, raw_packet, read_for_strategy


@contextlib.contextmanager
def single_writer(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as f:
        if f.tell() == 0:
            f.write(b'0')
            f.flush()
        f.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]
        try:
            yield
        finally:
            f.seek(0)
            if os.name == 'nt':
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]


def run(config: Path, *, probe: bool = False, max_seconds: float | None = None,
        now_fn=None) -> dict:
    settings = load_config(config)
    def clock():
        return now_fn() if now_fn is not None else dt.datetime.now(TZ)
    now = clock()
    # Do not create production ready records from an off-hours connectivity probe.
    output = Path(settings['output'])
    database = Path(settings['database'])
    if probe:
        output = output / 'probes' / now.strftime('%Y%m%dT%H%M%S%f')
        database = output / 'market.sqlite'
    output.mkdir(parents=True, exist_ok=True)
    status_path = output / 'status.json'
    state = {'status': 'starting', 'phase': phase(now), 'as_of': str(now.date()),
             'auto_trade': False, 'probe': probe, 'pid': os.getpid(), 'symbols': [],
             'history_requests': 0, 'symbol_errors': {}, 'quote_requests': 0,
             'bar_requests': 0, 'reconnects': 0, 'database': str(database),
             **{k: settings[k] for k in ('confirmation_seconds', 'quote_max_age_seconds',
                                        'heartbeat_max_age_seconds')}}

    def publish(**changes):
        state.update(changes)
        state['heartbeat'] = clock().isoformat()
        state['phase'] = phase(clock())
        atomic_json(status_path, state)

    with single_writer(database.with_suffix('.lock')):
        publish()
        try:
            from quant.data.refresh import latest_session
            last_session = latest_session(data_root=Path(settings['data_root']),
                                          through=now.date())
            is_session = last_session == now.date()
            state['is_trading_day'] = is_session
            if not probe and (not is_session or phase(now) in ('before_start', 'closed')):
                publish(status='idle', reason='Outside collection session')
                return state
            previous = latest_session(data_root=Path(settings['data_root']),
                                      through=now.date() - dt.timedelta(days=1))
            selection = watchlist(settings, now.date(), previous_session=previous)
            state['symbols'] = selection['symbols']
            atomic_json(output / 'watchlist.json', selection)
            if not state['symbols']:
                publish(status='idle', reason='Empty watch list')
                return state
        except Exception as exc:
            publish(status='failed', error=f'{type(exc).__name__}: {exc}')
            raise
        store = FeedStore(database)
        fallback = None
        if settings.get('public_fallback', False):
            from quant.data.realtime_fallback import FallbackFeed
            fallback = FallbackFeed(settings, store)
        client = None
        start = time.monotonic()
        due_bars: dict[str, float] = {}
        k1m_active: list[str] = []
        k1m_cursor = 0
        k1m_slots = 0
        k1m_rotate_due = 0.0
        quote_due = health_due = retry_at = 0.0
        failure_streak = 0
        probed = set()
        rotate_seconds = int(settings.get('k1m_rotate_seconds', 65))

        def apply_k1m_batch(batch: list[str], *, cursor: int) -> None:
            nonlocal k1m_active, k1m_cursor, due_bars, k1m_rotate_due
            assert client is not None
            drop = [s for s in k1m_active if s not in batch]
            add = [s for s in batch if s not in k1m_active]
            if drop:
                state['quota'] = client.unsubscribe_k1m(drop)
            if add:
                # Reserve already held as unused remain after initial quote/k budgeting.
                state['quota'] = client.subscribe_k1m(add)
            k1m_active = list(batch)
            k1m_cursor = cursor
            due_bars = {s: due_bars.get(s, 0.0) for s in k1m_active}
            for symbol in add:
                due_bars[symbol] = 0.0
            k1m_rotate_due = time.monotonic() + rotate_seconds
            state['k1m_active'] = list(k1m_active)
            state['k1m_cursor'] = k1m_cursor

        try:
            while max_seconds is None or time.monotonic() - start < max_seconds:
                now, tick = clock(), time.monotonic()
                if not probe and (now.date() != dt.date.fromisoformat(state['as_of'])
                                  or phase(now) == 'closed'):
                    break
                if not probe and phase(now) == 'lunch':
                    publish(status='running')
                    time.sleep(5)
                    continue
                if fallback is not None:
                    fallback.tick(state['symbols'], now, state, probe=probe)
                if tick < retry_at:
                    publish(status='running' if fallback else 'reconnecting', primary_available=False)
                    time.sleep(min(1, retry_at - tick))
                    continue
                try:
                    if client is None:
                        publish(status='connecting')
                        client = FutuRealtime(settings['host'], settings['port'])
                        state['provider_state'] = client.state()
                        admitted = fit_quota(selection, remaining=int(client.quota()['remain']),
                                             reserve=settings['quota_reserve'])
                        state['symbols'] = admitted['symbols']
                        k1m_slots = int(admitted['k1m_slots'])
                        state['k1m_slots'] = k1m_slots
                        state['quote_slots'] = admitted['quote_slots']
                        state['k1m_refresh_seconds'] = k1m_refresh_seconds(
                            len(state['symbols']), k1m_slots, rotate_seconds)
                        atomic_json(output / 'watchlist.json', admitted)
                        # QUOTE for the full admitted set; leftover quota rotates K_1M.
                        state['quota'] = client.subscribe_quotes(
                            state['symbols'], settings['quota_reserve'])
                        batch, k1m_cursor = next_k1m_batch(state['symbols'], k1m_slots, 0)
                        k1m_active = []
                        due_bars = {}
                        apply_k1m_batch(batch, cursor=k1m_cursor)
                        quote_due = health_due = 0.0
                    if (k1m_slots < len(state['symbols']) and k1m_slots > 0
                            and tick >= k1m_rotate_due):
                        batch, nxt = next_k1m_batch(state['symbols'], k1m_slots, k1m_cursor)
                        apply_k1m_batch(batch, cursor=nxt)
                        state['k1m_rotations'] = state.get('k1m_rotations', 0) + 1
                    if tick >= health_due:
                        state['provider_state'] = client.state()
                        server = float(state['provider_state']['timestamp'])
                        if abs(now.timestamp() - server) > 10:
                            raise ValueError('Local/provider clock skew exceeds 10 seconds')
                        health_due = tick + 15
                    if tick >= quote_due:
                        rows = client.quotes(state['symbols'])
                        received = clock()
                        raw = raw_packet(Path(settings['data_root']), 'quote', rows, received)
                        errors = store.quotes(rows, received, raw, state['symbols'])
                        state['quote_requests'] += 1
                        state['quote_errors'] = errors
                        seen = {row['code'].split('.')[1] + '.' + row['code'].split('.')[0]
                                for row in rows}
                        state['missing_quote_symbols'] = sorted(set(state['symbols']) - seen)
                        state['quote_age_seconds'] = {
                            row['code']: round((received - dt.datetime.fromisoformat(
                                row['data_date'] + 'T' + row['data_time']).replace(
                                    tzinfo=TZ)).total_seconds(), 3) for row in rows}
                        if errors or state['missing_quote_symbols']:
                            raise ValueError('Quote response has invalid or missing symbols')
                        quote_due = tick + settings['quote_poll_seconds']
                    # Only poll bars for the active K_1M window; stagger across the batch.
                    if due_bars:
                        symbol = min(due_bars, key=lambda s: due_bars[s])
                        if tick >= due_bars[symbol]:
                            try:
                                rows = client.bars(symbol)
                                if not rows:
                                    raise ValueError('Empty current K-line response')
                                received = clock()
                                raw = raw_packet(Path(settings['data_root']), 'k1m', rows, received)
                                result = store.bars(rows, symbol, received, raw,
                                                    settings['confirmation_seconds'],
                                                    session_date=last_session if probe else None)
                                state['bar_requests'] += 1
                                state.setdefault('last_bar_result', {})[symbol] = result
                                if result['errors']:
                                    raise ValueError(str(result['errors'][:3]))
                                state['symbol_errors'].pop(symbol, None)
                                state.setdefault('last_bar_fetch', {})[symbol] = received.isoformat()
                                probed.add(symbol)
                            except Exception as exc:
                                state['symbol_errors'][symbol] = f'{type(exc).__name__}: {exc}'
                            due_bars[symbol] = tick + settings['bar_poll_seconds']
                    failure_streak = 0
                    publish(status='probe' if probe else 'running', error=None, primary_available=True)
                    if probe and state.get('quote_requests', 0) > 0:
                        # Short probes cover the active K window; full-list needs longer rotate.
                        targets = k1m_active if k1m_active else []
                        if not targets or len(probed | set(state['symbol_errors'])) >= len(targets):
                            break
                    time.sleep(1)
                except Exception as exc:
                    failure_streak += 1
                    publish(status='reconnecting', error=f'{type(exc).__name__}: {exc}')
                    if client is not None:
                        client.close()
                        client = None
                    k1m_active = []
                    due_bars = {}
                    state['reconnects'] += 1
                    # Closed SDK connections retain quota for a minute. Avoid rapid churn.
                    retry_at = time.monotonic() + min(300, 65 * failure_streak)
                    if probe:
                        break
        finally:
            if fallback is not None:
                fallback.close()
            if client is not None:
                client.close()
            store.close()
            failed = state['status'] == 'reconnecting' or bool(state['symbol_errors']) or (
                probe and set(state['symbols']) != probed)
            publish(status=('probe_failed' if failed else 'probe_complete') if probe else 'stopped')
        return state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['run', 'probe', 'status', 'read'], nargs='?', default='run')
    parser.add_argument('--config', type=Path, default=Path('configs/data/realtime.toml'))
    parser.add_argument('--max-seconds', type=float)
    parser.add_argument('--symbol')
    parser.add_argument('--count', type=int, default=20)
    args = parser.parse_args()
    if args.action in ('run', 'probe'):
        result = run(args.config, probe=args.action == 'probe', max_seconds=args.max_seconds)
    else:
        settings = load_config(args.config)
        path = Path(settings['output']) / 'status.json'
        if args.action == 'status':
            result = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'status': 'not_started'}
            if 'heartbeat' in result:
                age = (dt.datetime.now(TZ) - dt.datetime.fromisoformat(result['heartbeat'])).total_seconds()
                result['heartbeat_age_seconds'] = age
                result['heartbeat_fresh'] = 0 <= age <= settings['heartbeat_max_age_seconds']
        else:
            if not args.symbol:
                parser.error('read requires --symbol')
            result = read_for_strategy(Path(settings['database']), path, args.symbol,
                                       now=dt.datetime.now(TZ), count=args.count)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get('status') in ('failed', 'probe_failed'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
