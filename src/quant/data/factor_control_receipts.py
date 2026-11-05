"""Recover monthly companion controls independently of cached factor panels."""
import datetime as dt
import hashlib
import json
import time
import uuid
from pathlib import Path

import polars as pl
from quant.data.realtime_store import atomic_json


def _coverage(path: Path, columns: tuple[str, ...]) -> dict | None:
    record = path.with_suffix('.coverage.json')
    if not path.is_file() or not record.is_file():
        return None
    try:
        saved = json.loads(record.read_text(encoding='utf-8'))
        if saved['columns'] != list(columns) or saved['sha256'] != hashlib.sha256(path.read_bytes()).hexdigest():
            return None
        start, end = dt.date.fromisoformat(saved['start']), dt.date.fromisoformat(saved['end'])
        if start > end:
            return None
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return {**saved, 'start': start, 'end': end}


def pending_control_start(path: Path, *, start: dt.date, end: dt.date,
                          columns: tuple[str, ...]) -> dt.date | None:
    """No receipt, partial write or changed content requires a fresh control export."""
    saved = _coverage(path, columns)
    if saved is None or saved['start'] > start or saved['end'] < start-dt.timedelta(days=1):
        return start
    if saved['end'] >= end:
        return None
    return saved['end']+dt.timedelta(days=1)


def write_control_receipt(path: Path, frame: pl.DataFrame, *, start: dt.date, end: dt.date,
                          columns: tuple[str, ...]) -> None:
    """Upsert controls and publish coverage last, without changing factor/label panels."""
    frame = frame.select('symbol', 'trade_date', *columns)
    if frame.filter(~pl.col('trade_date').is_between(start, end)).height:
        raise ValueError('Companion controls outside their computed interval')
    saved = _coverage(path, columns)
    covered_start, covered_end = start, end
    if saved is not None:
        old = pl.read_parquet(path).select('symbol', 'trade_date', *columns)
        frame = pl.concat([old.filter(~pl.col('trade_date').is_between(start, end)), frame])
        if start <= saved['end']+dt.timedelta(days=1) and end >= saved['start']-dt.timedelta(days=1):
            covered_start, covered_end = min(start, saved['start']), max(end, saved['end'])
    frame = frame.sort('symbol', 'trade_date')
    if frame.select('symbol', 'trade_date').is_duplicated().any():
        raise ValueError('Duplicate companion control keys')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.partial.parquet')
    try:
        frame.write_parquet(temporary)
        digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
        for attempt in range(11):
            try:
                temporary.replace(path)
                break
            except PermissionError:
                if attempt == 10:
                    raise
                time.sleep(.1)
    finally:
        temporary.unlink(missing_ok=True)
    # Coverage is published last; a failed receipt remains a cache miss.
    atomic_json(path.with_suffix('.coverage.json'), {'start': str(covered_start), 'end': str(covered_end),
        'columns': list(columns), 'rows': frame.height,
        'sha256': digest})
