"""Freeze GP's auxiliary five-minute inputs independently of live collectors."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil

from quant.data.realtime_store import atomic_json

POLICY = 'fixed_auxiliary_five_minute_bytes_v1'


def _hash(path):
    before = path.stat()
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f'Frozen GP minute source changed: {path}')
    return digest


def freeze(data_root: Path, output: Path) -> tuple[Path, list[Path]]:
    """Pin present files and absences once; additions/replacements stay outside.

    Collectors publish by atomic replacement. Same-volume hard links preserve
    the old bytes without doubling storage; copy is the cross-volume fallback.
    All snapshot bytes are hashed and checked again on every resume. No source
    file, existing snapshot, or missing source is overwritten or filled.
    """
    completed = output/'completed.json'
    output.mkdir(parents=True, exist_ok=True)
    if completed.exists():
        saved = json.loads(completed.read_text(encoding='utf-8'))
        if saved['policy'] != POLICY or saved['data_root'] != str(data_root.resolve()):
            raise ValueError('Frozen GP minute snapshot contract changed')
        paths = []
        for row in saved['files']:
            path = output/row['relative']
            path.resolve().relative_to(output.resolve())
            if not path.is_file() or _hash(path) != row['sha256']:
                raise ValueError(f'Frozen GP minute source checksum changed: {path}')
            paths.append(path)
        actual = sorted(str(p.relative_to(output)) for source in ('baostock','tdx')
            for p in (output/f'clean/bar_intraday/freq=5m/source={source}').glob('symbol=*/data.parquet'))
        if actual != sorted(row['relative'] for row in saved['files']):
            raise ValueError('Frozen GP minute source inventory changed')
        return output, [completed, *paths]
    inventory = output/'inventory.json'
    if inventory.exists():
        selected = json.loads(inventory.read_text(encoding='utf-8'))
        if selected['data_root'] != str(data_root.resolve()):
            raise ValueError('Frozen GP minute snapshot root changed')
    else:
        rows = []
        for source in ('baostock','tdx'):
            for path in sorted((data_root/f'clean/bar_intraday/freq=5m/source={source}').glob('symbol=*/data.parquet')):
                stat = path.stat()
                rows.append(dict(relative=str(path.relative_to(data_root)),bytes=stat.st_size,mtime_ns=stat.st_mtime_ns))
        selected = dict(data_root=str(data_root.resolve()), selected_at=dt.datetime.now(dt.UTC).isoformat(), files=rows)
        atomic_json(inventory, selected)
    rows = []
    for row in selected['files']:
        from quant.research.slice_budget import checkpoint
        checkpoint()
        source, target = data_root/row['relative'], output/row['relative']
        source.resolve().relative_to(data_root.resolve())
        target.resolve().relative_to(output.resolve())
        if not target.exists():
            stat = source.stat()
            if (stat.st_size,stat.st_mtime_ns) != (row['bytes'],row['mtime_ns']):
                raise ValueError(f'Frozen GP minute source changed: {source}')
            target.parent.mkdir(parents=True,exist_ok=True)
            try:
                os.link(source,target)
            except OSError:
                temporary = target.with_suffix('.partial.parquet')
                shutil.copy2(source,temporary)
                temporary.replace(target)
        stat = target.stat()
        if (stat.st_size,stat.st_mtime_ns) != (row['bytes'],row['mtime_ns']):
            raise ValueError(f'Frozen GP minute source changed: {target}')
        rows.append(dict(relative=row['relative'],sha256=_hash(target),bytes=stat.st_size))
    atomic_json(completed,dict(policy=POLICY,data_root=str(data_root.resolve()),files=rows,
        selected_at=selected['selected_at'],completed_at=dt.datetime.now(dt.UTC).isoformat()))
    return output, [completed, *(output/row['relative'] for row in rows)]
