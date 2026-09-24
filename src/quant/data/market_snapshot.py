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


def capture(output, *, batch_size=100, workers=3):
    latest = json.loads(Path('artifacts/daily/market_context/latest.json').read_text(encoding='utf-8'))
    history = Path(latest['report']).parent
    reference = history/'latest_reference.parquet'
    digest = hashlib.sha256(reference.read_bytes()).hexdigest()
    symbols = sorted(pl.read_parquet(reference)['symbol'].unique().to_list())
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
                atomic_json(root/'latest.json', dict(status='complete', output=str(output),
                    as_of=result['completed_at'], coverage=result['diagnostic']['coverage'],
                    market_state=result['diagnostic']['market_state'], auto_trade=False))
            except Exception as exc:
                atomic_json(root/'latest.json', dict(status='failed', output=str(output),
                    as_of=dt.datetime.now(TZ).isoformat(), error=f'{type(exc).__name__}: {exc}', auto_trade=False))
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
