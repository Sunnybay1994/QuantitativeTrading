"""Existing quote-task companion: local ETF paper orders, bounded read-only quotes."""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
import time
from pathlib import Path

import polars as pl

from quant.data.connectors.public_market import PublicMarket
from quant.data.realtime_inputs import TZ
from quant.data.realtime_store import atomic_json, raw_packet
from quant.execution.b16_forward import (ROOT, SYMBOLS, clock, daily, finalize, read,
                                        scenarios, settings, submit)
from quant.execution.manual_session_service import instance_lock


def normalize(rows, received, limits):
    quotes, rejected = [], []
    for row in rows:
        symbol = '.'.join(reversed(row['code'].split('.')))
        try:
            if symbol not in SYMBOLS or row.get('depth_unit') != 'lots_100_sdk_truncated':
                raise ValueError('missing_verified_depth_units')
            provider = dt.datetime.fromisoformat(row['data_date']+'T'+row['data_time']).replace(tzinfo=TZ)
            age = (received-provider).total_seconds()
            if not 0 <= age <= 10 or provider.date() != received.date():
                raise ValueError('stale_or_future_quote')
            if symbol not in limits:
                raise ValueError('missing_official_limits')
            quote = dict(symbol=symbol, provider_time=provider.isoformat(), received_at=received.isoformat(),
                bid=float(row['bid1_price']), ask=float(row['ask1_price']),
                bid_size=float(row['bid1_lots'])*100, ask_size=float(row['ask1_lots'])*100,
                suspended=bool(row['suspension']), **limits[symbol])
            if any(not math.isfinite(quote[k]) or quote[k] <= 0 for k in
                   ('bid','ask','bid_size','ask_size','up_limit','down_limit')):
                raise ValueError('missing_or_invalid_depth')
            if quote['suspended'] or not quote['down_limit'] <= quote['bid'] <= quote['ask'] <= quote['up_limit']:
                raise ValueError('crossed_suspended_or_out_of_band')
            # Repeated polls of the SAME provider observation cannot replenish capacity.
            quote['quote_id'] = hashlib.sha256(json.dumps({k:v for k,v in quote.items()
                if k != 'received_at'}, sort_keys=True).encode()).hexdigest()
            quotes.append(quote)
        except (ValueError, TypeError, KeyError) as exc:
            rejected.append(dict(symbol=symbol, reason=str(exc)))
    return quotes, rejected


def saved_limits(data_root, day):
    from quant.data.etf_limits import read_limits, validate_limits
    bands = read_limits(data_root).filter((pl.col('trade_date') == day) & pl.col('symbol').is_in(SYMBOLS))
    validate_limits(bands)
    return {r['symbol']: {k:r[k] for k in ('up_limit','down_limit')} for r in bands.to_dicts()}


def capture(client, root, data_root, limits, *, probe=False):
    rows = client.fetch('quotes', SYMBOLS, 'tushare_sina')
    received = dt.datetime.now(TZ)
    raw = raw_packet(data_root, 'b16_depth', rows, received, source='tushare_sina')
    quotes, rejected = normalize(rows, received, limits)
    # Across packet files keep only the first received copy of a provider observation.
    destination = root/('probe_quotes' if probe else 'quotes')/str(received.date())
    seen = {q['quote_id'] for p in destination.glob('*.json') for q in read(p)['quotes']}
    fresh = [q for q in quotes if q['quote_id'] not in seen]
    packet = dict(received_at=received.isoformat(), raw=raw, quotes=fresh, rejected=rejected,
                  duplicate_observations=len(quotes)-len(fresh), probe=probe, auto_trade=False)
    atomic_json(destination/f'{received:%H%M%S%f}.json', packet)
    return dict(received_at=received.isoformat(), accepted=len(fresh), rejected=rejected, raw=raw)


def step(root, data_root, now, limits):
    """Called repeatedly and on restart. Submission and completion are persisted once."""
    cfg = settings(root)
    day = now.date()
    if day < cfg['first_execution_date']:
        return dict(status='pending_first_execution', first_execution=str(cfg['first_execution_date']))
    with instance_lock(root/'forward.lock'):
        for folder, delay, cost in scenarios(root):
            directory = folder/str(day)
            if not (directory/'signal.json').exists():
                continue
            if not (directory/'submission.json').exists():
                result = submit(read(directory/'signal.json'), day, now, delay, limits)
                if result is not None:
                    atomic_json(directory/'submission.json', result)
        if now >= clock(day, '09:40'):
            # The previous complete daily snapshot carries known corporate actions;
            # never use execution-day close/volume as intraday execution inputs.
            calendar = pl.read_parquet(data_root/'clean/trade_calendar/market=SH/data.parquet')
            sessions = sorted(set(calendar.filter(pl.col('is_open'))['date'].to_list()))
            if day not in sessions:
                return dict(status='non_session')
            prior = max(d for d in sessions if d < day)
            path = data_root/f'clean/etf_cross_asset/b20_forward_{prior:%Y%m%d}/dividends.parquet'
            dividends = pl.read_parquet(path)
            for folder, _, _ in scenarios(root):
                directory = folder/str(day)
                if (directory/'signal.json').exists() and not (directory/'execution.json').exists():
                    state = read(folder/'state.json')
                    if state['date'] != str(prior):
                        raise ValueError('Execution requires the immediately prior closing account')
                    finalize(folder, day, sessions, dividends, calendar)
    return dict(status='cancelled_at_deadline' if now >= clock(day, '09:40') else 'watching',
                official_limit_symbols=sorted(limits))


def run(*, root=ROOT, data_root=Path('data'), probe=False, once=False):
    cfg = settings(root)
    started = dt.datetime.now(TZ)
    output = root/'probes'/started.strftime('%Y%m%dT%H%M%S%f') if probe else root
    output.mkdir(parents=True, exist_ok=True)
    client = PublicMarket()
    try:
        with instance_lock(output/'service.lock'):
            if probe:
                result = capture(client, output, data_root, saved_limits(data_root, started.date()), probe=True)
                result.update(status='read_only_probe', formal_fills=0, auto_trade=False)
                atomic_json(output/'status.json', result)
                return result
            limits, refresh_attempt, recovered = {}, 0., False
            while True:
                now = dt.datetime.now(TZ)
                state = dict(at=now.isoformat(), pid=os.getpid(), auto_trade=False, model_only=True)
                try:
                    if now.date() != started.date():
                        return state
                    if now.date() >= cfg['first_execution_date']:
                        calendar = pl.read_parquet(data_root/'clean/trade_calendar/market=SH/data.parquet')
                        sessions = calendar.filter(pl.col('is_open'))['date'].to_list()
                        if now.date() not in sessions:
                            state['status'] = 'non_session'
                            atomic_json(root/'service_status.json', state)
                            return state
                        # Recover missed daily closures from complete existing publications only.
                        prior = max(d for d in sessions if d < now.date())
                        if not recovered:
                            daily(end=prior, root=root, data_root=data_root)
                            recovered = True
                        limits = saved_limits(data_root, now.date())
                        if len(limits) != 3 and time.monotonic()-refresh_attempt > 60:
                            refresh_attempt = time.monotonic()
                            from quant.data.etf_limits import refresh_limits
                            refresh_limits(data_root=data_root, symbols=SYMBOLS, start=now.date(), end=now.date())
                            limits = saved_limits(data_root, now.date())
                    now = dt.datetime.now(TZ)
                    state.update(step(root, data_root, now, limits))
                    if (now.date() >= cfg['first_execution_date'] and clock(now.date(),'09:30') <= now < clock(now.date(),'09:40')
                            and any((f/str(now.date())/'submission.json').exists() for f,_,_ in scenarios(root))):
                        state['capture'] = capture(client, root, data_root, limits)
                except Exception as exc:
                    state.update(status='input_unavailable', error=f'{type(exc).__name__}: {exc}')
                atomic_json(root/'service_status.json', state)
                if once or now < clock(now.date(), '09:20') or now >= clock(now.date(), '09:41'):
                    return state
                time.sleep(5)
    finally:
        client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--probe', action='store_true')
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--close', type=dt.date.fromisoformat)
    args = parser.parse_args()
    result = daily(end=args.close, root=args.root, data_root=args.data_root) if args.close else run(
        root=args.root, data_root=args.data_root, probe=args.probe, once=args.once)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
