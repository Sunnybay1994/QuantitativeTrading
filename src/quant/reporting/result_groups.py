"""Presentation-only grouping from saved account histories, never rounded metrics."""
from collections import Counter, OrderedDict
import hashlib
import json
from functools import lru_cache
from pathlib import Path
import tempfile
from threading import Lock

import polars as pl

_CONTENT_DIGESTS: OrderedDict[str, str] = OrderedDict()
_CONTENT_LOCK = Lock()
_CONTENT_LIMIT = 16384
_NAV_COLUMNS = ['date', 'unit_nav', 'equity', 'cash', 'market_value']
_CACHE_VERSION = 1


def _file_identity(path: Path) -> list[int] | None:
    try:
        stat = path.stat()
        return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns]
    except OSError:
        return None


def _dependencies_current(dependencies: dict) -> bool:
    return all(_file_identity(Path(path)) == identity for path, identity in dependencies.items())


@lru_cache(maxsize=16384)
def _digest(path: str, size: int, modified: int, device: int, inode: int) -> str:
    # Many reports save byte-identical benchmark histories under different paths.
    # Reuse their validated semantic digest, retaining only hashes in this cache.
    # Read one immutable byte buffer so hashing and validation see the same file.
    data = Path(path).read_bytes()
    content = hashlib.sha256(data).hexdigest()
    with _CONTENT_LOCK:
        if content in _CONTENT_DIGESTS:
            _CONTENT_DIGESTS.move_to_end(content)
            return _CONTENT_DIGESTS[content]
    frame = pl.read_parquet(data, columns=_NAV_COLUMNS).sort('date')
    if frame.is_empty() or frame['date'].n_unique() != frame.height:
        raise ValueError('Incomplete account history')
    # One vectorized check instead of four separate eager query executions.
    values = pl.col(_NAV_COLUMNS[1:])
    if frame.select(pl.any_horizontal(values.is_null() | ~values.is_finite()).any()).item():
        raise ValueError('Invalid account history')
    digest = hashlib.sha256(frame.write_json().encode()).hexdigest()
    with _CONTENT_LOCK:
        _CONTENT_DIGESTS[content] = digest
        _CONTENT_DIGESTS.move_to_end(content)
        if len(_CONTENT_DIGESTS) > _CONTENT_LIMIT:
            _CONTENT_DIGESTS.popitem(last=False)
    return digest


def annotate(rows: list[dict], root: Path, *, dependencies: dict | None = None) -> list[dict]:
    groups = {}
    dependencies = dependencies if dependencies is not None else {}
    artifacts = (root/'artifacts').resolve()
    resolved = {}
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
        dependencies[str(evidence.absolute())] = _file_identity(evidence)
        try:
            paths = json.loads(evidence.read_text(encoding='utf-8'))['nav']
            if not paths:
                continue
            signatures, sources = [], []
            for cost in ('0.5', '1', '2'):
                for name in paths:
                    parts = list(Path(name).parts)
                    parts[parts.index('cost_1')] = 'cost_'+cost
                    source = root/Path(*parts)
                    dependencies[str(source.absolute())] = _file_identity(source)
                    if source not in resolved:
                        resolved[source] = source.resolve()
                    path = resolved[source]
                    if not path.is_relative_to(artifacts):
                        raise ValueError('Account outside artifacts')
                    stat = path.stat()
                    signatures.append(_digest(str(path), stat.st_size, stat.st_mtime_ns,
                                              stat.st_dev, stat.st_ino))
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


def _annotations(serialized: str, root: str) -> list[dict]:
    root_path = Path(root).resolve()
    cache = root_path/'artifacts/reports/dashboard/result_groups.json'
    key = hashlib.sha256(serialized.encode()).hexdigest()
    original = json.loads(serialized)
    try:
        saved = json.loads(cache.read_text(encoding='utf-8'))
        annotations = saved['annotations']
        if (saved['version'] == _CACHE_VERSION and saved['registry_key'] == key
                and saved['root'] == str(root_path) and len(annotations) == len(original)
                and all(set(row) == {'is_control', 'result_group', 'group_kind'} for row in annotations)
                and _dependencies_current(saved['dependencies'])):
            return annotations
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass  # A derived cache is optional; source verification remains authoritative.
    dependencies = {}
    rows = annotate(original, root_path, dependencies=dependencies)
    annotations = [{k: row[k] for k in ('is_control', 'result_group', 'group_kind')} for row in rows]
    saved = {'version': _CACHE_VERSION, 'registry_key': key, 'root': str(root_path),
             'dependencies': dependencies, 'annotations': annotations}
    temporary = None
    try:
        # Never publish a cache whose source changed during its computation.
        if _dependencies_current(dependencies):
            cache.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', dir=cache.parent, prefix='result_groups.',
                                             suffix='.tmp', encoding='utf-8', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(saved, stream, ensure_ascii=False)
            temporary.replace(cache)
    except OSError:
        pass
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return annotations


def cached_annotations(rows: list[dict], root: Path) -> list[dict]:
    # Registry keys and source file identities invalidate even a cache from a prior process.
    keys = ('run_path', 'variant', 'report_path', 'cagr_1x', 'sharpe_1x', 'mdd_1x', 'turnover_1x')
    serialized = json.dumps([{k: row.get(k) for k in keys} for row in rows], sort_keys=True)
    for row, annotation in zip(rows, _annotations(serialized, str(root)), strict=True):
        row.update(annotation)
    return rows
