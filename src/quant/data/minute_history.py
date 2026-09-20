"""Slow all-market Futu history queue; recent refresh never spends history quota."""

import argparse
import datetime as dt
import json
import time
import tomllib
from pathlib import Path

import polars as pl

from quant.data.connectors.futu_history import history_page, history_quota
from quant.data.connectors.futu_realtime import FutuRealtime
from quant.data.connectors.public_market import PublicMarket
from quant.data.futu_minute_backfill import download_year
from quant.data.realtime import single_writer
from quant.data.realtime_store import atomic_json
from quant.data.recent_minutes import universe


def earliest_available(context, symbol, start, end, root, cache):
    """First ascending history page supplies the actual lower bound, not a guessed year."""
    saved = cache.get(symbol, {})
    if saved.get('requested_start') == start and saved.get('requested_end') == end:
        return saved['first_date']
    time.sleep(2.1)
    frame, next_key = history_page(context, symbol, start, end, None)
    raw = root / 'raw/futu/earliest_bounds' / f'symbol={symbol}' / (dt.datetime.now().strftime('%Y%m%dT%H%M%S%f') + '.parquet')
    raw.parent.mkdir(parents=True, exist_ok=True)
    with raw.open('xb') as stream:
        pl.from_pandas(frame).write_parquet(stream)
    if frame.empty:
        raise ValueError('No history returned for full requested interval')
    times = frame['time_key'].astype(str).to_list()
    if times != sorted(times) or set(frame['code']) != {FutuRealtime.code(symbol)}:
        raise ValueError('Unexpected history pagination order or symbol')
    first = times[0][:10]
    if not start <= first <= end:
        raise ValueError('History lower bound outside requested interval')
    cache[symbol] = dict(requested_start=start, requested_end=end, first_date=first,
                         rows=len(frame), has_more=bool(next_key), raw=str(raw),
                         discovered_at=dt.datetime.now().isoformat())
    return first


def run(config: Path, *, check_only=False):
    settings = tomllib.loads(config.read_text(encoding='utf-8'))
    if settings.get('auto_trade') is not False:
        raise ValueError('auto_trade=false required')
    root, output = Path(settings['data_root']), Path(settings['output'])
    output.mkdir(parents=True, exist_ok=True)
    with single_writer(output / 'writer.lock'):
        public = PublicMarket(timeout=25)
        try:
            members = universe(public, Path(settings['recent_output']), root)
        finally:
            public.close()
        start, end = settings['start'], settings['end']
        discover = settings.get('earliest_available', False)
        bounds_path = output / 'earliest_bounds.json'
        bounds = json.loads(bounds_path.read_text()) if bounds_path.exists() else {}
        progress_path = output / 'progress.json'
        progress = json.loads(progress_path.read_text()) if progress_path.exists() else {}
        existing: dict[str, set[int]] = {}
        for path in (root / 'clean/futu_minute').glob('*/symbol=*/year=*/data.parquet'):
            existing.setdefault(path.parent.parent.name[7:], set()).add(int(path.parent.name[5:]))
        pending = []
        unsupported = []
        for member in members:
            symbol = member['symbol']
            if (progress.get(symbol, {}).get('retry_start') == start
                    and progress.get(symbol, {}).get('retry_after', '') > dt.datetime.now().isoformat()):
                continue
            if symbol.endswith('.BJ'):
                unsupported.append(symbol)
                continue
            listing = member.get('list_date') or start.replace('-', '')
            first = max(start, dt.datetime.strptime(listing, '%Y%m%d').date().isoformat())
            saved = bounds.get(symbol, {})
            if discover and saved.get('requested_start') == first and saved.get('requested_end') == end:
                first = max(first, saved['first_date'])
            if first > end:
                continue
            years = [year for year in range(int(end[:4]), int(first[:4])-1, -1)
                     if year not in existing.get(symbol, set()) and progress.get(symbol, {}).get(
                         'empty_years', {}).get(str(year), '') <= dt.datetime.now().isoformat()]
            if discover:
                years.sort()  # Preserve the oldest retrievable window before it rolls away.
            if years:
                pending.append(dict(symbol=symbol, start=first, years=years))
        status = dict(start=start, end=end, earliest_available=discover, pending_symbols=len(pending),
                      unsupported_symbols=unsupported, results=[], errors=[], auto_trade=False)
        if check_only:
            status['status'] = 'planned'
            atomic_json(output / 'plan.json', dict(**status, queue=pending))
            return status
        client = FutuRealtime()
        began, new_symbols = time.monotonic(), 0
        try:
            used, remaining, charged = history_quota(client.context)
            status['quota_before'] = dict(used=used, remaining=remaining)
            pending.sort(key=lambda m: (m['symbol'] not in charged,
                                        progress.get(m['symbol'], {}).get('attempted_at', '')))
            for item in pending:
                if time.monotonic() - began >= settings['max_seconds']:
                    status['pause_reason'] = 'time_budget'
                    break
                symbol = item['symbol']
                used, remaining, charged = history_quota(client.context)
                if symbol not in charged:
                    if remaining <= settings['quota_reserve'] or new_symbols >= settings['max_new_symbols']:
                        status['pause_reason'] = 'quota_or_daily_budget'
                        break
                    new_symbols += 1
                if discover:
                    try:
                        listing = next(m.get('list_date') for m in members if m['symbol'] == symbol)
                        request_start = max(start, dt.datetime.strptime(listing, '%Y%m%d').date().isoformat()) if listing else start
                        first = earliest_available(client.context, symbol, request_start, end, root, bounds)
                        atomic_json(bounds_path, bounds)
                        item['start'] = max(item['start'], first)
                        item['years'] = [year for year in item['years'] if year >= int(first[:4])]
                        status.setdefault('earliest_dates', {})[symbol] = first
                    except Exception as exc:
                        status['errors'].append(dict(symbol=symbol, stage='earliest_probe', error=str(exc)))
                        progress.setdefault(symbol, {}).update(attempted_at=dt.datetime.now().isoformat(),
                            retry_start=start, retry_after=(dt.datetime.now()+dt.timedelta(days=1)).isoformat())
                        atomic_json(progress_path, progress)
                        continue
                for year in item['years']:
                    if time.monotonic() - began >= settings['max_seconds']:
                        status['pause_reason'] = 'time_budget'
                        break
                    begin, finish = max(item['start'], f'{year}-01-01'), min(end, f'{year}-12-31')
                    raw = root / 'raw/futu/minute_backfill' / f'symbol={symbol}' / f'year={year}' / dt.datetime.now().strftime('%Y%m%dT%H%M%S%f')
                    clean = root / 'clean/futu_minute/all_market' / f'symbol={symbol}' / f'year={year}/data.parquet'
                    try:
                        result = download_year(client.context, symbol, begin, finish, raw, clean)
                        status['results'].append(result)
                        progress.setdefault(symbol, {}).update(attempted_at=dt.datetime.now().isoformat())
                        if result.get('empty'):
                            progress[symbol].setdefault('empty_years', {})[str(year)] = (
                                dt.datetime.now()+dt.timedelta(days=7)).isoformat()
                            continue  # A suspended/empty year does not prove a history boundary.
                    except Exception as exc:
                        status['errors'].append(dict(symbol=symbol, year=year, error=str(exc)))
                        progress.setdefault(symbol, {}).update(attempted_at=dt.datetime.now().isoformat(), retry_start=start,
                            retry_after=(dt.datetime.now()+dt.timedelta(days=7)).isoformat())
                        break
                    finally:
                        atomic_json(progress_path, progress)
                        atomic_json(output / 'status.json', status)
            used, remaining, _ = history_quota(client.context)
            status.update(status='paused' if status.get('pause_reason') else 'checked',
                          quota_after=dict(used=used, remaining=remaining), newly_charged_attempts=new_symbols)
        finally:
            client.close()
            atomic_json(output / 'status.json', status)
        return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('configs/data/minute_history.toml'))
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    result = run(args.config, check_only=args.check_only)
    print(json.dumps({k: v for k, v in result.items() if k not in ('results', 'unsupported_symbols')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
