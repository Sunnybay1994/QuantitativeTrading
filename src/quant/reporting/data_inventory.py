"""Incremental local quote inventory from Parquet evidence, not directory dates."""
import datetime as dt
import threading
import time
import tomllib

import polars as pl
import pyarrow.parquet as pq

from quant.data.realtime_store import atomic_json


def read(path):
    import json
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}


def files(root):
    data = root / 'data/clean'
    paths = []
    for folder in ('bar_intraday', 'futu_minute', 'bar_1d', 'bar_1d_tdx'):
        paths.extend((data / folder).rglob('*.parquet'))
    cfg = root / 'configs/data/refresh.toml'
    if cfg.exists():
        snapshot = tomllib.loads(cfg.read_text(encoding='utf-8'))['stock_snapshot']
        paths.extend((data / 'tushare_bulk/snapshots' / snapshot / 'bar_1d').rglob('*.parquet'))
    paths.extend((data / 'tushare_incremental').glob('date=*/bar_1d.parquet'))
    return sorted({p for p in paths if not p.name.startswith('.') and '.tmp' not in p.name})


def profile(path, root):
    meta = pq.read_metadata(path)
    if not meta.num_rows:
        return None
    names = meta.schema.names
    date = next((c for c in ('trade_date', 'date', 'bar_time', 'bar_start') if c in names), None)
    if date is None or 'symbol' not in names:
        raise ValueError('Missing symbol/date columns')
    def extrema(column):
        values = [meta.row_group(i).column(names.index(column)).statistics for i in range(meta.num_row_groups)]
        if values and all(s is not None and s.has_min_max for s in values):
            return min(s.min for s in values), max(s.max for s in values)
        frame = pl.read_parquet(path, columns=[column])
        return frame[column].min(), frame[column].max()
    start, end = extrema(date)
    if start is None or end is None:
        raise ValueError('No non-null dates')
    lo, hi = extrema('symbol')
    symbols = [lo] if lo == hi else pl.read_parquet(path, columns=['symbol'])['symbol'].drop_nulls().unique().to_list()
    parts = dict(part.split('=', 1) for part in path.parts if '=' in part)
    source = parts.get('source')
    if not source and 'source' in names:
        lo, hi = extrema('source')
        source = lo if lo == hi else 'mixed'
    source = source or 'unknown'
    frequency = parts.get('freq', '1m' if 'futu_minute' in path.parts else '1d')
    return dict(path=path.relative_to(root).as_posix(), frequency=frequency, source=source,
                first=str(start)[:10], last=str(end)[:10], symbols=symbols, rows=meta.num_rows,
                year=int(parts['year']) if 'futu_minute' in path.parts else None)


def summarize(entries, root):
    groups, minute = {}, {}
    universe = {m['symbol']: m for m in read(root/'artifacts/minute_refresh/universe.json').get('members', [])}
    bounds = read(root/'artifacts/minute_history/earliest_bounds.json')
    config = root/'configs/data/minute_history.toml'
    settings = tomllib.loads(config.read_text(encoding='utf-8')) if config.exists() else {}
    target_end = settings.get('end', '')
    for row in entries:
        key = (row['frequency'], row['source'])
        group = groups.setdefault(key, dict(frequency=key[0], source=key[1], first=row['first'], last=row['last'], symbols=set(), files=0))
        group['first'], group['last'] = min(group['first'], row['first']), max(group['last'], row['last'])
        group['symbols'].update(row['symbols'])
        group['files'] += 1
        if row['frequency'] != '1m':
            continue
        for symbol in row['symbols']:
            item = minute.setdefault(symbol, dict(symbol=symbol, name=universe.get(symbol, {}).get('name', ''),
                in_universe=symbol in universe, first=row['first'], last=row['last'], sources=set(), years=set()))
            item['first'], item['last'] = min(item['first'], row['first']), max(item['last'], row['last'])
            item['sources'].add(row['source'])
            if row['source'] == 'futu' and row['year'] is not None:
                item['years'].add(row['year'])
    for symbol, item in minute.items():
        first = bounds.get(symbol, {}).get('first_date')
        expected = set(range(int(first[:4]), int(target_end[:4])+1)) if first and target_end else set()
        item.update(earliest_available=first, target_end=target_end,
            missing_years=sorted(expected-item['years']), plan_years_complete=bool(expected) and expected <= item['years'],
            latest_reached=bool(target_end) and item['last'] >= target_end)
        item['years'], item['sources'] = sorted(item['years']), sorted(item['sources'])
    return dict(overview=[{**v, 'symbols': len(v['symbols'])} for _, v in sorted(groups.items())],
        minute_symbols=sorted(minute.values(), key=lambda m: (not m['plan_years_complete'], m['symbol'])),
        universe_total=len(universe), stored_minute_universe=sum(m['in_universe'] for m in minute.values()),
        plan_years_complete=sum(m['plan_years_complete'] for m in minute.values()), target_end=target_end)


class DataInventory:
    def __init__(self, root, ttl=300):
        self.root, self.ttl = root, ttl
        self.output = root/'artifacts/dashboard_data'
        self.lock = threading.Lock()
        self.payload = read(self.output/'inventory.json')
        self.running, self.at, self.scanned, self.total, self.error = False, 0., 0, 0, None

    def get(self, force=False):
        with self.lock:
            if not self.running and (force or time.monotonic()-self.at > self.ttl):
                self.running = True
                self.error = None
                threading.Thread(target=self._build, daemon=True).start()
            return {**self.payload, 'scan': dict(running=self.running, scanned=self.scanned,
                total=self.total, error=self.error), 'has_snapshot': bool(self.payload)}

    def _build(self):
        try:
            cached = read(self.output/'file_index.json')
            index, errors = {}, []
            paths = files(self.root)
            self.total, self.scanned = len(paths), 0
            for path in paths:
                key = path.relative_to(self.root).as_posix()
                try:
                    stat = path.stat()
                    signature = [stat.st_size, stat.st_mtime_ns]
                    old = cached.get(key, {})
                    value = old.get('value') if old.get('signature') == signature else profile(path, self.root)
                    after = path.stat()
                    if signature != [after.st_size, after.st_mtime_ns]:
                        raise ValueError('File changed during scan; retry next refresh')
                    index[key] = dict(signature=signature, value=value)
                except (OSError, ValueError, pl.exceptions.PolarsError) as exc:
                    errors.append(dict(path=key, error=type(exc).__name__))
                self.scanned += 1
            payload = summarize([v['value'] for v in index.values() if v['value']], self.root)
            payload.update(updated_at=dt.datetime.now().astimezone().isoformat(), errors=errors,
                           files=len(index), coverage_note='日期是已存记录的边界，不代表期间连续完整。计划年份齐全仅指各年已有历史分区，逐日缺口未核验。')
            atomic_json(self.output/'file_index.json', index)
            atomic_json(self.output/'inventory.json', payload)
            with self.lock:
                self.payload, self.at = payload, time.monotonic()
        except Exception as exc:
            self.error = type(exc).__name__
            self.at = time.monotonic()
        finally:
            self.running = False


def collection_status(root):
    recent = read(root/'artifacts/minute_refresh/status.json')
    history = read(root/'artifacts/minute_history/status.json')
    realtime = read(root/'artifacts/realtime/futu/status.json')
    return dict(baostock=read(root/'artifacts/baostock_history/status.json'),
        recent={k: recent.get(k) for k in ('status', 'stage', 'as_of', 'completed', 'total', 'universe_total', 'changed_rows', 'heartbeat', 'source_errors')},
        history={**{k: history.get(k) for k in ('status', 'start', 'end', 'pending_symbols', 'pause_reason', 'quota_before', 'quota_after')},
                 'saved_partitions_this_run': len(history.get('results', [])), 'errors': len(history.get('errors', []))},
        realtime={k: realtime.get(k) for k in ('status', 'heartbeat', 'phase', 'primary_available')})
