"""Resumable mainland-wide recent 1m capture, with explicit incomplete-session reports."""

import argparse
import datetime as dt
import json
import math
import time
import tomllib
from pathlib import Path

import polars as pl

from quant.data.connectors.public_market import PublicMarket
from quant.data.intraday import merge_bars
from quant.data.intraday_bars import SCHEMA, TZ, validate_bars
from quant.data.realtime import single_writer
from quant.data.realtime_store import atomic_json, raw_packet


def normalize(rows, symbol, source, end):
    values, rejected = [], 0
    for row in rows:
        try:
            code, market = symbol.split('.')
            if row['code'] != f'{market}.{code}':
                raise ValueError('Wrong symbol')
            stamp = dt.datetime.fromisoformat(row['time_key']).replace(tzinfo=TZ)
            minute = stamp.hour * 60 + stamp.minute
            if stamp.date() > end:
                continue
            # Opening-auction rows are preserved in raw, not inserted into regular 240 bars.
            if minute == 570:
                continue
            if stamp.second or minute not in (*range(571, 691), *range(781, 901)):
                raise ValueError('Unexpected minute label')
            value = dict(symbol=symbol, trade_date=stamp.date(), bar_start=stamp-dt.timedelta(minutes=1),
                bar_end=stamp, source=source, amount=row['turnover'],
                **{k: row[k] for k in ('open', 'high', 'low', 'close', 'volume')})
            prices = [value[k] for k in ('open', 'high', 'low', 'close')]
            if (any(not math.isfinite(p) or p <= 0 for p in prices)
                    or value['high'] < max(prices) or value['low'] > min(prices)
                    or not math.isfinite(value['volume']) or value['volume'] < 0):
                raise ValueError('Invalid OHLCV')
            if value['amount'] is not None and (not float('-inf') < value['amount'] < float('inf')
                                               or value['amount'] < 0):
                raise ValueError('Invalid amount')
            values.append(value)
        except (KeyError, ValueError, TypeError):
            rejected += 1
    frame = pl.DataFrame(values, schema=SCHEMA)
    return validate_bars(frame), rejected


def universe(client, output, root):
    path = output / 'universe.json'
    try:
        members = client.fetch('universe', [], 'tushare_catalog')
        if not members or len({m['symbol'] for m in members}) != len(members):
            raise ValueError('Invalid universe response')
        if any(not m['symbol'].endswith(('.SH', '.SZ', '.BJ')) for m in members):
            raise ValueError('Non-mainland symbol')
        snapshot = root / 'raw/tushare_minute_universe' / (dt.datetime.now().strftime('%Y%m%dT%H%M%S%f') + '.json')
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        with snapshot.open('x', encoding='utf-8') as stream:
            json.dump(members, stream, ensure_ascii=False)
        atomic_json(path, dict(members=members, captured_at=dt.datetime.now(TZ).isoformat(), raw=str(snapshot)))
    except Exception:
        if not path.exists():
            raise
        saved = json.loads(path.read_text(encoding='utf-8'))
        if (dt.datetime.now(TZ) - dt.datetime.fromisoformat(saved['captured_at'])).days > 7:
            raise ValueError('Universe cache older than seven days') from None
        members = saved['members']
    return sorted(members, key=lambda m: m['symbol'])


def coverage(root, symbol, dates):
    rows = []
    for source in ('tdx', 'akshare_sina', 'akshare_eastmoney'):
        path = root / 'clean/bar_intraday/freq=1m' / f'source={source}' / f'symbol={symbol}/data.parquet'
        if not path.exists():
            continue
        frame = pl.read_parquet(path).filter(pl.col('trade_date').is_in(dates))
        for day, part in frame.group_by('trade_date'):
            rows.append(dict(date=str(day[0]), source=source, bars=part['bar_start'].n_unique(),
                             amount_complete=part['amount'].null_count() == 0))
    return rows


def run(config, *, limit=None, skip_tdx=False, max_seconds=None):
    if (limit is not None and limit < 1) or (max_seconds is not None and max_seconds <= 0):
        raise ValueError('Positive limit and time budget required')
    settings = tomllib.loads(config.read_text(encoding='utf-8'))
    if settings.get('auto_trade') is not False:
        raise ValueError('auto_trade=false required')
    root, output = Path(settings['data_root']), Path(settings['output'])
    output.mkdir(parents=True, exist_ok=True)
    with single_writer(output / 'writer.lock'):
        from quant.data.refresh import latest_session
        now = dt.datetime.now(TZ)
        through = now.date() if now.time() >= dt.time(16) else now.date()-dt.timedelta(days=1)
        end = latest_session(data_root=root, through=through)
        client = PublicMarket(timeout=25)
        began = time.monotonic()
        state = dict(status='running', as_of=str(end), started_at=now.isoformat(), auto_trade=False,
                     completed=0, total=0, changed_rows=0, results=[], source_errors={})
        def publish():
            state['heartbeat'] = dt.datetime.now(TZ).isoformat()
            atomic_json(output / 'status.json', state)
        publish()
        try:
            members = universe(client, output, root)
            state['universe_total'] = len(members)
            if limit:
                members = members[:limit]
            state['total'] = len(members)
            state['stage'] = 'tdx_import' if not skip_tdx else 'public_sources'
            publish()
            if not skip_tdx and Path(settings['tdx_root']).exists():
                from quant.data.tdx_intraday import import_tdx_intraday
                state['tdx'] = import_tdx_intraday(tdx_root=Path(settings['tdx_root']), data_root=root,
                    artifacts_root=output / 'tdx', workers=2)
            state['stage'] = 'public_sources'
            publish()
            calendar = pl.read_parquet(root / 'clean/trade_calendar/market=SH/data.parquet')
            dates = sorted(calendar.filter(pl.col('is_open') & (pl.col('date') <= end))['date'].to_list())[-10:]
            checkpoints = output / f'date={end}'
            checkpoints.mkdir(exist_ok=True)
            failures, retry_at = {}, {}
            # Rotate after the most recently attempted symbol on interrupted runs.
            members.sort(key=lambda m: (checkpoints / (m['symbol'] + '.json')).stat().st_mtime
                         if (checkpoints / (m['symbol'] + '.json')).exists() else 0)
            for member in members:
                if max_seconds and time.monotonic()-began >= max_seconds:
                    state['status'] = 'time_budget_reached'
                    break
                symbol = member['symbol']
                checkpoint = checkpoints / (symbol + '.json')
                prior = json.loads(checkpoint.read_text()) if checkpoint.exists() else {}
                result = dict(symbol=symbol, sources={}, changed_rows=0)
                for source in settings['sources']:
                    previous = prior.get('sources', {}).get(source, {})
                    if previous.get('returned_rows', 0) > 0 and previous.get('last_date') == str(end):
                        result['sources'][source] = previous
                        continue
                    if time.monotonic() < retry_at.get(source, 0):
                        result['sources'][source] = dict(deferred='source_backoff')
                        continue
                    try:
                        rows = client.fetch('bars', [symbol], source)
                        raw = raw_packet(root, 'recent_1m', rows, dt.datetime.now(TZ), source=source)
                        frame, rejected = normalize(rows, symbol, source, end)
                        if frame.is_empty():
                            raise ValueError('No valid completed bars')
                        directory = root / 'clean/bar_intraday/freq=1m' / f'source={source}' / f'symbol={symbol}'
                        changed = merge_bars(directory, frame)
                        result['changed_rows'] += changed
                        result['sources'][source] = dict(returned_rows=len(rows), valid_rows=frame.height,
                            rejected_rows=rejected, changed_rows=changed, raw=raw,
                            first_date=str(frame['trade_date'].min()), last_date=str(frame['trade_date'].max()),
                            amount_missing_rows=frame['amount'].null_count())
                        failures[source] = 0
                    except Exception as exc:
                        result['sources'][source] = dict(error=str(exc))
                        failures[source] = failures.get(source, 0) + 1
                        state['source_errors'][source] = state['source_errors'].get(source, 0) + 1
                        if failures[source] >= 3:
                            retry_at[source] = time.monotonic() + 300
                    time.sleep(settings['request_spacing_seconds'])
                result['coverage'] = coverage(root, symbol, dates)
                complete = {r['date'] for r in result['coverage'] if r['bars'] == 240}
                amount_complete = {r['date'] for r in result['coverage'] if r['bars'] == 240 and r['amount_complete']}
                listing = str(member.get('list_date') or '')
                expected = [str(d) for d in dates if not listing or d.strftime('%Y%m%d') >= listing]
                result['missing_or_suspended_dates'] = sorted(set(expected) - complete)
                result['missing_amount_complete_dates'] = sorted(set(expected) - amount_complete)
                atomic_json(checkpoint, result)
                state['completed'] += 1
                state['changed_rows'] += result['changed_rows']
                state['results'].append(dict(symbol=symbol, changed_rows=result['changed_rows'],
                    missing_days=len(result['missing_or_suspended_dates']), checkpoint=str(checkpoint)))
                if state['completed'] % 10 == 0:
                    print(f"Recent minutes {state['completed']}/{state['total']} changed={state['changed_rows']}", flush=True)
                publish()
            else:
                state['status'] = 'checked'
            state['coverage_complete'] = (state['completed'] == state['universe_total']
                                         and not any(r['missing_days'] for r in state['results']))
        except Exception as exc:
            state.update(status='failed', error=str(exc))
            raise
        finally:
            client.close()
            publish()
        return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('configs/data/recent_minutes.toml'))
    parser.add_argument('--limit', type=int)
    parser.add_argument('--skip-tdx', action='store_true')
    parser.add_argument('--max-seconds', type=float)
    args = parser.parse_args()
    result = run(args.config, limit=args.limit, skip_tdx=args.skip_tdx, max_seconds=args.max_seconds)
    print(json.dumps({k: v for k, v in result.items() if k != 'results'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
