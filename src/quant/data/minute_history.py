"""Slow all-market Futu history queue; recent refresh never spends history quota."""

import argparse
import datetime as dt
import json
import time
import tomllib
from pathlib import Path

from quant.data.connectors.futu_history import history_quota
from quant.data.connectors.futu_realtime import FutuRealtime
from quant.data.connectors.public_market import PublicMarket
from quant.data.futu_minute_backfill import download_year
from quant.data.realtime import single_writer
from quant.data.realtime_store import atomic_json
from quant.data.recent_minutes import universe


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
        progress_path = output / 'progress.json'
        progress = json.loads(progress_path.read_text()) if progress_path.exists() else {}
        existing: dict[str, set[int]] = {}
        for path in (root / 'clean/futu_minute').glob('*/symbol=*/year=*/data.parquet'):
            existing.setdefault(path.parent.parent.name[7:], set()).add(int(path.parent.name[5:]))
        pending = []
        unsupported = []
        for member in members:
            symbol = member['symbol']
            if progress.get(symbol, {}).get('retry_after', '') > dt.datetime.now().isoformat():
                continue
            if symbol.endswith('.BJ'):
                unsupported.append(symbol)
                continue
            listing = member.get('list_date') or start.replace('-', '')
            first = max(start, dt.datetime.strptime(listing, '%Y%m%d').date().isoformat())
            if first > end:
                continue
            years = [year for year in range(int(end[:4]), int(first[:4])-1, -1)
                     if year not in existing.get(symbol, set())]
            if years:
                pending.append(dict(symbol=symbol, start=first, years=years))
        status = dict(start=start, end=end, pending_symbols=len(pending),
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
                for year in item['years']:
                    begin, finish = max(item['start'], f'{year}-01-01'), min(end, f'{year}-12-31')
                    raw = root / 'raw/futu/minute_backfill' / f'symbol={symbol}' / f'year={year}' / dt.datetime.now().strftime('%Y%m%dT%H%M%S%f')
                    clean = root / 'clean/futu_minute/all_market' / f'symbol={symbol}' / f'year={year}/data.parquet'
                    try:
                        result = download_year(client.context, symbol, begin, finish, raw, clean)
                        status['results'].append(result)
                        progress[symbol] = dict(attempted_at=dt.datetime.now().isoformat())
                        if result.get('empty'):
                            progress[symbol]['retry_after'] = (dt.datetime.now()+dt.timedelta(days=7)).isoformat()
                            break
                    except Exception as exc:
                        status['errors'].append(dict(symbol=symbol, year=year, error=str(exc)))
                        progress[symbol] = dict(attempted_at=dt.datetime.now().isoformat(),
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
