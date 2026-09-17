"""Presentation-only grouping from saved account histories, never rounded metrics."""
from collections import Counter
import hashlib
import json
from functools import lru_cache
from pathlib import Path

import polars as pl


@lru_cache(maxsize=16384)
def _digest(path: str, size: int, modified: int) -> str:
    frame = pl.read_parquet(path).select('date', 'unit_nav', 'equity', 'cash', 'market_value').sort('date')
    if frame.is_empty() or frame['date'].is_duplicated().any():
        raise ValueError('Incomplete account history')
    if any(frame[c].null_count() or not frame[c].is_finite().all()
           for c in ('unit_nav', 'equity', 'cash', 'market_value')):
        raise ValueError('Invalid account history')
    return hashlib.sha256(frame.write_json().encode()).hexdigest()


def annotate(rows: list[dict], root: Path) -> list[dict]:
    groups = {}
    def metrics(row):
        return tuple(row.get(k) for k in ('cagr_1x', 'sharpe_1x', 'mdd_1x', 'turnover_1x'))
    counts = Counter(metrics(row) for row in rows)
    for row in rows:
        row['is_control'] = row['variant'] == 'control'
        row['result_group'] = None
        row['group_kind'] = ''
        if counts[metrics(row)] < 2 or any(v is None for v in metrics(row)):
            continue
        key = hashlib.sha256(row['variant'].encode()).hexdigest()[:16]
        evidence = root/row['report_path']
        evidence = evidence.parent/'periods_1x'/key/'sources.json'
        try:
            paths = json.loads(evidence.read_text(encoding='utf-8'))['nav']
            if not paths:
                continue
            signatures, sources = [], []
            for cost in ('0.5', '1', '2'):
                for name in paths:
                    parts = list(Path(name).parts)
                    parts[parts.index('cost_1')] = 'cost_'+cost
                    path = (root/Path(*parts)).resolve()
                    if not path.is_relative_to((root/'artifacts').resolve()):
                        raise ValueError('Account outside artifacts')
                    stat = path.stat()
                    signatures.append(_digest(str(path), stat.st_size, stat.st_mtime_ns))
                    sources.append(str(path))
            fingerprint = hashlib.sha256('|'.join(signatures).encode()).hexdigest()
            row['result_group'] = fingerprint
            groups.setdefault(fingerprint, []).append((row, tuple(sources)))
        except (OSError, ValueError, KeyError, pl.exceptions.PolarsError):
            continue  # No verified history means no grouping, even if metrics match.
    for group in groups.values():
        if len(group) < 2:
            continue
        same_source = len({paths for _, paths in group}) == 1
        control = any(row['is_control'] for row, _ in group)
        kind = '同源报告' if same_source else '公共对照／相同净值' if control else '相同净值结果'
        for row, _ in group:
            row['group_kind'] = kind
    return rows


@lru_cache(maxsize=2)
def _annotations(serialized: str, root: str) -> list[dict]:
    rows = annotate(json.loads(serialized), Path(root))
    return [{k: row[k] for k in ('is_control', 'result_group', 'group_kind')} for row in rows]


def cached_annotations(rows: list[dict], root: Path) -> list[dict]:
    # Only completed immutable histories are grouped. Registry changes invalidate this cache.
    keys = ('run_path', 'variant', 'report_path', 'cagr_1x', 'sharpe_1x', 'mdd_1x', 'turnover_1x')
    serialized = json.dumps([{k: row.get(k) for k in keys} for row in rows], sort_keys=True)
    for row, annotation in zip(rows, _annotations(serialized, str(root)), strict=True):
        row.update(annotation)
    return rows
