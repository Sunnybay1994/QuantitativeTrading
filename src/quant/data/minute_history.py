# -*- coding: utf-8 -*-
"""All-market Futu multi-year history queue; maximize the ~100-symbol quota.

Recent / same-day minutes must not compete for this quota: use
`quant data minutes` (TDX + AkShare) and realtime instead. Optional
same_day_topup remains in code but stays off in config so a rolling
7-day re-charge cannot crowd out missing historical symbols.
"""

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
from quant.data.futu_minute_backfill import download_range_merge, download_year
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


def inventory_year_paths(root: Path) -> dict[str, dict[int, Path]]:
    """symbol -> {year: clean parquet path}; prefer all_market when duplicated."""
    found: dict[str, dict[int, Path]] = {}
    for path in (root / 'clean/futu_minute').glob('*/symbol=*/year=*/data.parquet'):
        symbol = path.parent.parent.name[7:]
        year = int(path.parent.name[5:])
        bucket = found.setdefault(symbol, {})
        prior = bucket.get(year)
        if prior is None or 'all_market' in path.parts:
            bucket[year] = path
    return found


def symbol_last_date(year_paths: dict[int, Path]) -> dt.date | None:
    last = None
    for path in year_paths.values():
        value = pl.scan_parquet(path).select(pl.col('trade_date').max()).collect().item()
        if value is None:
            continue
        day = value if isinstance(value, dt.date) else dt.date.fromisoformat(str(value)[:10])
        if last is None or day > last:
            last = day
    return last


def clean_path_for_year(root: Path, inventory: dict[str, dict[int, Path]],
                        symbol: str, year: int) -> Path:
    existing = inventory.get(symbol, {}).get(year)
    if existing is not None:
        return existing
    return root / 'clean/futu_minute/all_market' / f'symbol={symbol}' / f'year={year}/data.parquet'


def liquid_mid_large(settings: dict) -> list[dict]:
    """Mid/large float by circulating MV, ordered by median amount (liquidity).

    Bands match artifacts/realtime/selection_20260919/build_watchlist.py:
    mid [mid_float_min, mid_float_max), large >= large_float_min.
    """
    ranking_path = Path(settings['liquidity_ranking'])
    caps_path = Path(settings['market_caps'])
    if not ranking_path.exists() or not caps_path.exists():
        return []
    ranking = pl.read_parquet(ranking_path)
    caps = pl.read_parquet(caps_path)
    mid_min = float(settings.get('mid_float_min', 10_000_000_000))
    mid_max = float(settings.get('mid_float_max', 50_000_000_000))
    large_min = float(settings.get('large_float_min', 50_000_000_000))
    limit = int(settings.get('liquid_mid_large_limit', 200))
    # Mid ∪ large float; sort by liquidity (median amount).
    joined = ranking.join(caps, on='symbol').filter(
        (
            pl.col('circulating_market_value').is_between(mid_min, mid_max, closed='left')
            | (pl.col('circulating_market_value') >= large_min)
        )
        & (~pl.col('symbol').str.ends_with('.BJ'))
    ).sort(['median_amount', 'symbol'], descending=[True, False])
    rows = []
    for row in joined.head(limit).to_dicts():
        mv = row['circulating_market_value']
        band = 'large' if mv >= large_min else 'mid'
        rows.append(dict(symbol=row['symbol'], median_amount=row['median_amount'],
                         circulating_market_value=mv, band=band))
    return rows


def same_day_queue(root: Path, end: str, settings: dict) -> list[dict]:
    """Priority A inventory gaps, then Priority B liquid mid/large gaps."""
    inventory = inventory_year_paths(root)
    end_date = dt.date.fromisoformat(end)
    queue: list[dict] = []
    seen: set[str] = set()

    for symbol, years in sorted(inventory.items()):
        if not symbol.endswith(('.HK', '.US')):
            continue
        last = symbol_last_date(years)
        if last is not None and last >= end_date:
            continue
        gap_start = (last + dt.timedelta(days=1)).isoformat() if last else end
        if gap_start > end:
            continue
        queue.append(dict(priority=0, symbol=symbol, gap_start=gap_start,
                          year=end_date.year, band='inventory',
                          clean=str(clean_path_for_year(root, inventory, symbol, end_date.year))))
        seen.add(symbol)

    for row in liquid_mid_large(settings):
        symbol = row['symbol']
        if symbol in seen or not symbol.endswith(('.HK', '.US')):
            continue
        years = inventory.get(symbol, {})
        last = symbol_last_date(years) if years else None
        if last is not None and last >= end_date:
            continue
        gap_start = (last + dt.timedelta(days=1)).isoformat() if last else end
        if gap_start > end:
            continue
        queue.append(dict(priority=1, symbol=symbol, gap_start=gap_start,
                          year=end_date.year, band=row['band'],
                          median_amount=row['median_amount'],
                          clean=str(clean_path_for_year(root, inventory, symbol, end_date.year))))
        seen.add(symbol)
    return queue


def run_same_day_topup(client, root: Path, end: str, settings: dict, status: dict,
                       progress: dict, progress_path: Path, began: float,
                       new_symbols: int) -> int:
    """Spend history quota on same-day gaps before opening new multi-year symbols."""
    queue = same_day_queue(root, end, settings)
    used, remaining, charged = history_quota(client.context)
    # Already-charged inventory first (free), then other A, then B by liquidity.
    queue.sort(key=lambda item: (
        item['priority'],
        item['symbol'] not in charged,
        -float(item.get('median_amount') or 0),
        item['symbol'],
    ))
    status['same_day'] = dict(
        pending=len(queue), results=[], errors=[],
        priority_a=sum(1 for i in queue if i['priority'] == 0),
        priority_b=sum(1 for i in queue if i['priority'] == 1),
    )
    atomic_json(Path(settings['output']) / 'same_day_plan.json',
                dict(end=end, queue=queue, auto_trade=False))
    for item in queue:
        if time.monotonic() - began >= settings['max_seconds']:
            status['pause_reason'] = 'time_budget'
            break
        symbol = item['symbol']
        used, remaining, charged = history_quota(client.context)
        if symbol not in charged:
            if remaining <= settings.get('quota_reserve', 0):
                status['pause_reason'] = 'quota_exhausted'
                break
            if new_symbols >= settings['max_new_symbols']:
                status['pause_reason'] = 'max_new_symbols'
                break
            new_symbols += 1
        raw = (root / 'raw/futu/minute_same_day' / f'symbol={symbol}'
               / f'year={item["year"]}' / dt.datetime.now().strftime('%Y%m%dT%H%M%S%f'))
        clean = Path(item['clean'])
        try:
            result = download_range_merge(
                client.context, symbol, item['gap_start'], end, raw, clean)
            result.update(priority=item['priority'], band=item['band'])
            status['same_day']['results'].append(result)
            progress.setdefault(symbol, {}).update(
                attempted_at=dt.datetime.now().isoformat(),
                same_day_end=end)
        except Exception as exc:
            status['same_day']['errors'].append(
                dict(symbol=symbol, gap_start=item['gap_start'], error=str(exc)))
            progress.setdefault(symbol, {}).update(
                attempted_at=dt.datetime.now().isoformat(),
                retry_after=(dt.datetime.now() + dt.timedelta(days=1)).isoformat())
        finally:
            atomic_json(progress_path, progress)
            atomic_json(Path(settings['output']) / 'status.json', status)
        if status.get('pause_reason'):
            break
    return new_symbols


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
        start = settings['start']
        end = settings['end']
        if settings.get('end_policy') == 'latest_completed_session':
            from quant.data.refresh import latest_session
            now = dt.datetime.now()
            through = now.date() if now.time() >= dt.time(16) else now.date() - dt.timedelta(days=1)
            end = latest_session(data_root=root, through=through).isoformat()
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
            if not symbol.endswith(('.HK', '.US')):
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
        same_day_pending = same_day_queue(root, end, settings) if settings.get('same_day_topup', False) else []
        status = dict(start=start, end=end, earliest_available=discover, pending_symbols=len(pending),
                      unsupported_symbols=unsupported, results=[], errors=[], auto_trade=False,
                      same_day_pending=len(same_day_pending))
        if check_only:
            status['status'] = 'planned'
            atomic_json(output / 'plan.json', dict(**status, queue=pending, same_day_queue=same_day_pending))
            return status
        client = FutuRealtime()
        began, new_symbols = time.monotonic(), 0
        try:
            used, remaining, charged = history_quota(client.context)
            status['quota_before'] = dict(used=used, remaining=remaining)
            if settings.get('same_day_topup', False):
                new_symbols = run_same_day_topup(
                    client, root, end, settings, status, progress, progress_path,
                    began, new_symbols)
                if status.get('pause_reason'):
                    used, remaining, _ = history_quota(client.context)
                    status.update(status='paused', quota_after=dict(used=used, remaining=remaining),
                                  newly_charged_attempts=new_symbols)
                    return status
            used, remaining, charged = history_quota(client.context)
            pending.sort(key=lambda m: (m['symbol'] not in charged,
                                        progress.get(m['symbol'], {}).get('attempted_at', '')))
            for item in pending:
                if time.monotonic() - began >= settings['max_seconds']:
                    status['pause_reason'] = 'time_budget'
                    break
                symbol = item['symbol']
                used, remaining, charged = history_quota(client.context)
                if symbol not in charged:
                    # Exhaust remaining quota (reserve may be 0); max_new_symbols is a hard cap.
                    if remaining <= settings.get('quota_reserve', 0):
                        status['pause_reason'] = 'quota_exhausted'
                        break
                    if new_symbols >= settings['max_new_symbols']:
                        status['pause_reason'] = 'max_new_symbols'
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
