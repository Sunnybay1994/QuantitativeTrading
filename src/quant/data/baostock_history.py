"""Full-market BaoStock 5m history, bounded resumable yearly requests."""
import argparse
import datetime as dt
import json
import time
from pathlib import Path

import polars as pl

from quant.data.connectors.baostock import BaostockConnector
from quant.data.connectors.baostock_access import BaoStockAccessPaused
from quant.data.intraday import _complete_stock_dates, _directory, add_session_quality, merge_bars
from quant.data.intraday_bars import TZ, normalize_baostock
from quant.data.market_universe import bao_members, listing
from quant.data.realtime import single_writer
from quant.data.realtime_store import atomic_json
from quant.data.storage import RawStore


def pending(prior, end, now):
    if not prior:
        return True
    if prior.get('status') == 'captured' and prior.get('through', '') >= str(end):
        return False
    retry = prior.get('retry_after')
    return not retry or dt.datetime.fromisoformat(retry) <= now


def capture(root, row, start, end, expected):
    symbol = row['symbol']
    directory = _directory(root, 'baostock', symbol, '5m')
    with single_writer(directory/'writer.lock'):
        path = directory/'data.parquet'
        existing = pl.read_parquet(path).filter(pl.col('trade_date').is_between(start, end)) if path.exists() else None
        if expected and existing is not None and set(expected) <= _complete_stock_dates(existing):
            return dict(status='captured', changed_rows=0, reused=True, rows=existing.height)
        raw = BaostockConnector().fetch_intraday(symbol, start, end)
        saved = RawStore(root/'raw').write(source='baostock_intraday', table=symbol, frame=raw,
            parameters=dict(symbol=symbol, frequency='5m', start=str(start), end=str(end)))
        frame = normalize_baostock(raw, symbol).filter(pl.col('trade_date').is_between(start, end))
        frame = add_session_quality(frame, root, '5m', symbol)
        changed = merge_bars(directory, frame) if frame.height else 0
        available = pl.concat([existing, frame], how='diagonal_relaxed') if existing is not None else frame
        missing = sorted(set(expected)-_complete_stock_dates(available))
        partial = frame.filter(~pl.col('session_complete'))['trade_date'].n_unique()
        return dict(status='partial' if missing or partial else 'captured' if frame.height and expected else
                    'unverified' if frame.height else 'empty', changed_rows=changed, rows=frame.height,
                    raw=str(saved.data_path), missing_traded_dates=list(map(str, missing)), incomplete_days=partial)


def run(root=Path('data'), output=Path('artifacts/baostock_history'), max_seconds=3000, limit=None):
    from quant.data.refresh import completed_date, latest_session
    from quant.data.refresh_stocks import read_stock_data
    now = dt.datetime.now(TZ)
    end = latest_session(data_root=root, through=completed_date('today', now))
    with single_writer(output/'writer.lock'):
        rows = bao_members(root)
        atomic_json(output/'universe.json', dict(captured_at=now.isoformat(), members=rows))
        state = dict(status='running', started_at=now.isoformat(), as_of=str(end), total_symbols=len(rows),
                     requests=0, changed_rows=0, errors=0, auto_trade=False)
        began = time.monotonic()
        def publish():
            state['heartbeat'] = dt.datetime.now(TZ).isoformat()
            atomic_json(output/'status.json', state)
        publish()
        consecutive_errors = 0
        # First broaden current-year coverage, then walk backwards to each listing.
        # Past empty/partial responses have a cooldown, never a completed marker.
        for year in range(end.year, 1989, -1):
            year_end = min(end, dt.date(year, 12, 31))
            daily = None
            expected = {}
            for row in rows:
                from quant.core.capital_window import CapitalPathPause, checkpoint as capital_checkpoint
                try:
                    capital_checkpoint(data_root=root)
                except CapitalPathPause as exc:
                    state.update(status='paused',pause_reason=str(exc))
                    publish()
                    return state
                start = max(dt.date(year, 1, 1), listing(row), dt.date(1990, 12, 19))
                stop = min(year_end, dt.date.fromisoformat(row['delist_date'])) if row.get('delist_date') else year_end
                if start > stop:
                    continue
                checkpoint = output/'checkpoints'/row['symbol']/f'{year}.json'
                prior = json.loads(checkpoint.read_text(encoding='utf-8')) if checkpoint.exists() else {}
                if not pending(prior, stop, dt.datetime.now(TZ)):
                    continue
                if time.monotonic()-began >= max_seconds or (limit is not None and state['requests'] >= limit):
                    state['status'] = 'paused'
                    publish()
                    return state
                if daily is None:
                    daily = read_stock_data(data_root=root, config=Path('configs/data/refresh.toml'),
                        table='bar_1d', start=dt.date(year, 1, 1), end=year_end)
                    expected = {s: g['trade_date'].to_list() for (s,), g in daily.filter(pl.col('volume') > 0).group_by('symbol')}
                state.update(symbol=row['symbol'], year=year)
                publish()
                try:
                    dates = [day for day in expected.get(row['symbol'], []) if start <= day <= stop]
                    result = capture(root, row, start, stop, dates)
                except BaoStockAccessPaused as exc:
                    state.update(status='paused', pause_reason='source_access_limit', error=str(exc))
                    publish()
                    return state  # Do not turn a source-wide pause into symbol failures.
                except Exception as exc:
                    result = dict(status='error', error=str(exc), changed_rows=0)
                    state['errors'] += 1
                result.update(symbol=row['symbol'], start=str(start), through=str(stop),
                              checked_at=dt.datetime.now(TZ).isoformat())
                if result['status'] != 'captured':
                    delay = dt.timedelta(minutes=10) if result['status'] == 'error' else dt.timedelta(days=7)
                    result['retry_after'] = (dt.datetime.now(TZ)+delay).isoformat()
                atomic_json(checkpoint, result)
                state['requests'] += 1
                state['changed_rows'] += result['changed_rows']
                consecutive_errors = consecutive_errors + 1 if result['status'] == 'error' else 0
                if consecutive_errors >= 5:
                    state.update(status='paused', pause_reason='consecutive_source_errors',
                                 consecutive_errors=consecutive_errors)
                    publish()
                    return state
                publish()
                time.sleep(0.3)
        state['status'] = 'pass_finished'  # Not a claim that every source returned complete data.
        publish()
        return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--max-seconds', type=int, default=3000)
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()
    if args.max_seconds <= 0 or (args.limit is not None and args.limit <= 0):
        parser.error('Positive limits required')
    print(json.dumps(run(max_seconds=args.max_seconds, limit=args.limit), ensure_ascii=False))


if __name__ == '__main__':
    main()
