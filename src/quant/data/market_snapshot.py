"""Bounded broad-market quote capture using the existing public transport and store."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt
import hashlib
import json
import time
from pathlib import Path

import polars as pl

from quant.data.connectors.public_market import PublicMarket
from quant.data.realtime_inputs import TZ
from quant.data.realtime_store import FeedStore, atomic_json, raw_packet
from quant.research.market_indicators_run import live


def _reference(context_path, data_root, now):
    """A quote capture requires this session's real prior-close receipt."""
    latest = json.loads(context_path.read_text(encoding='utf-8'))
    if not isinstance(latest, dict) or latest.get('status') != 'complete':
        reason = latest.get('reason', 'Market context incomplete') if isinstance(latest, dict) else 'Invalid market context'
        raise ValueError(reason)
    calendar = pl.read_parquet(data_root/'clean/trade_calendar/market=SH/data.parquet')
    previous = calendar.filter(pl.col('is_open') & (pl.col('date') < now.date()))['date'].max()
    if previous is None or latest.get('date') != str(previous) or latest.get('effective_date') != str(now.date()):
        raise ValueError('Market context is not for the preceding exchange session')
    receipt = latest.get('daily_completion')
    if not isinstance(receipt, dict) or not receipt.get('path') or not receipt.get('sha256'):
        raise ValueError('Completed live-data daily receipt missing')
    receipt_path = Path(receipt['path'])
    payload = receipt_path.read_bytes()
    saved = json.loads(payload)
    if (hashlib.sha256(payload).hexdigest() != receipt['sha256']
            or receipt_path.stat().st_mtime > now.timestamp()
            or not isinstance(saved, dict) or saved.get('as_of') != str(previous)
            or saved.get('status') != 'complete' or saved.get('saved_data') is not False
            or saved.get('rehearsal') is not False):
        raise ValueError('Daily receipt is stale, incomplete or changed')
    report = latest.get('report')
    if not isinstance(report, str) or not report:
        raise ValueError('Completed market context report missing')
    report_path = Path(report)
    if not report_path.is_file():
        raise ValueError('Market context report file missing')
    history = report_path.parent
    reference = history/'latest_reference.parquet'
    digest = hashlib.sha256(reference.read_bytes()).hexdigest()
    frame = pl.read_parquet(reference)
    if frame.is_empty() or frame['trade_date'].max() != previous:
        raise ValueError('Frozen reference is not from the preceding exchange session')
    symbols = sorted(frame['symbol'].unique().to_list())
    return history, reference, digest, symbols


def capture(output, *, batch_size=100, workers=3,
            context_path=Path('artifacts/daily/market_context/latest.json'), data_root=Path('data'), now=None):
    clock = now or dt.datetime.now(TZ)
    if clock.tzinfo is None:
        raise ValueError('Require timezone-aware capture clock')
    clock = clock.astimezone(TZ)
    try:
        history, reference, digest, symbols = _reference(context_path, data_root, clock)
    except (OSError, ValueError, KeyError, TypeError, pl.exceptions.PolarsError) as exc:
        output.mkdir(parents=True, exist_ok=False)
        result = dict(status='incomplete', market_state='unknown', reason=f'{type(exc).__name__}: {exc}',
            completed_at=clock.isoformat(), requested=0, received=0, auto_trade=False)
        atomic_json(output/'summary.json', result)
        atomic_json(output/'progress.json', result)
        return result
    if not symbols or batch_size < 1 or not 1 <= workers <= 4:
        raise ValueError('Require a nonempty frozen reference and bounded workers')
    output.mkdir(parents=True, exist_ok=False)
    store = FeedStore(output/'market.sqlite')
    errors = []

    def fetch(chunk):
        client = PublicMarket(timeout=20)
        try:
            return chunk, client.fetch('quotes', chunk, 'tushare_sina'), dt.datetime.now(TZ)
        finally:
            client.close()

    started = dt.datetime.now(TZ)
    atomic_json(output/'progress.json', dict(status='running', requested=len(symbols), started_at=started.isoformat()))
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            jobs = {pool.submit(fetch, symbols[i:i+batch_size]): symbols[i:i+batch_size]
                    for i in range(0, len(symbols), batch_size)}
            for count, future in enumerate(as_completed(jobs), 1):
                try:
                    requested, rows, received = future.result()
                    raw = raw_packet(Path('data'), 'quote', rows, received, source='tushare_sina')
                    errors.extend(store.quotes(rows, received, raw, requested))
                except Exception as exc:
                    errors.append(dict(symbols=jobs[future], error=f'{type(exc).__name__}: {exc}'))
                atomic_json(output/'progress.json', dict(status='running', requested=len(symbols),
                    started_at=started.isoformat(), completed_batches=count,
                    total_batches=len(jobs), failed_items=len(errors)))
                atomic_json(output/'capture_errors.json', dict(errors=errors))
        quotes = [json.loads(row[0]) for row in store.db.execute(
            'SELECT payload FROM quotes WHERE id IN (SELECT MAX(id) FROM quotes GROUP BY symbol)')]
    finally:
        store.close()
    if hashlib.sha256(reference.read_bytes()).hexdigest() != digest:
        raise RuntimeError('Reference changed during capture')
    quote_path = output/'quotes.json'
    quote_path.write_text(json.dumps(quotes, ensure_ascii=False), encoding='utf-8')
    now = dt.datetime.now(TZ)
    diagnostics = live(Path('configs/research/market_indicators_v1.toml'), history,
                       output/'diagnostic', now=now, quotes_path=quote_path)
    result = dict(status='complete', started_at=started.isoformat(), completed_at=now.isoformat(),
        elapsed_seconds=(now-started).total_seconds(), requested=len(symbols), received=len(quotes),
        scope='prior-session observed Shanghai/Shenzhen stock reference; excludes Beijing and ETFs',
        reference=str(reference), reference_sha256=digest,
        fields_present={key:sum(row.get(key) is not None for row in quotes) for key in ('prev_close','bid','ask')},
        amount_definition='cumulative_session_turnover_cny',
        errors=errors, diagnostic=json.loads((output/'diagnostic/snapshot.json').read_text(encoding='utf-8')),
        auto_trade=False)
    atomic_json(output/'summary.json', result)
    atomic_json(output/'progress.json', {k:v for k,v in result.items() if k not in ('errors','diagnostic')})
    return result


def session(root):
    from quant.data.realtime import single_writer
    from quant.data.realtime_inputs import phase
    from quant.data.refresh import latest_session
    root.mkdir(parents=True, exist_ok=True)
    with single_writer(root/'session.lock'):
        while True:
            now = dt.datetime.now(TZ)
            if latest_session(data_root=Path('data'), through=now.date()) != now.date() or phase(now) == 'closed':
                return
            if phase(now) != 'trading':
                time.sleep(30)
                continue
            started = time.monotonic()
            output = root/now.strftime('%Y%m%dT%H%M%S%f')
            try:
                result = capture(output)
                if result['status'] != 'complete':
                    atomic_json(root/'latest.json', dict(status='incomplete', output=str(output),
                        as_of=result['completed_at'], market_state='unknown', reason=result['reason'], auto_trade=False))
                else:
                    atomic_json(root/'latest.json', dict(status='complete', output=str(output),
                        as_of=result['completed_at'], coverage=result['diagnostic']['coverage'],
                        market_state=result['diagnostic']['market_state'], auto_trade=False))
            except Exception as exc:
                atomic_json(root/'latest.json', dict(status='failed', output=str(output),
                    as_of=dt.datetime.now(TZ).isoformat(), market_state='unknown',
                    error=f'{type(exc).__name__}: {exc}', auto_trade=False))
            # Bounded 5-minute snapshots, not a streaming/execution feed.
            while time.monotonic()-started < 300:
                time.sleep(max(0, min(30, 300-(time.monotonic()-started))))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--session', action='store_true')
    args = parser.parse_args()
    if args.session:
        session(args.output)
    else:
        result = capture(args.output)
        print(json.dumps({k:v for k,v in result.items() if k not in ('errors','diagnostic')}, ensure_ascii=False))
