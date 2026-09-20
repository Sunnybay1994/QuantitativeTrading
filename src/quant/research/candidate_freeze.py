"""Persist the actual freeze time of completed GP candidates; never backdate from mtime."""
from __future__ import annotations

import ast
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import tempfile
import tomllib


FORWARD_NOT_BEFORE = dt.date(2026, 9, 21)
_LOCAL_TIMEZONE = dt.timezone(dt.timedelta(hours=8), 'Asia/Shanghai')
_FORWARD_RULE = ('First exchange session strictly after frozen_local_date and on or after '
                 'forward_not_before; daily/calendar must resolve the actual session.')


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode('utf-8')


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _read_source(output: Path, relative: str) -> tuple[bytes, dict]:
    path = output / relative
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f'Candidate freeze source changed while reading: {relative}')
    return raw, {'path': relative, 'sha256': _sha(raw)}


def _identity(output: Path, forward_not_before: dt.date) -> dict:
    if type(forward_not_before) is not dt.date or forward_not_before < FORWARD_NOT_BEFORE:
        raise ValueError('Forward lower bound must be a date on or after 2026-09-21')
    search_raw, search_source = _read_source(output, 'search.json')
    contract_raw, contract_source = _read_source(output, 'search_contract.json')
    search, contract = json.loads(search_raw), json.loads(contract_raw)
    if contract.get('objective') != 'predictive_priority_v2':
        raise ValueError('Candidate freeze requires a completed predictive_priority_v2 search')
    if contract.get('config', {}).get('auto_trade', False) is not False:
        raise ValueError('Candidate freeze requires auto_trade=false')
    rows = search.get('candidates')
    if not isinstance(rows, list) or not rows:
        raise ValueError('Cannot freeze an empty candidate export')
    candidates, definitions, identifiers, expressions = [], [], set(), set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Invalid candidate record')
        identifier, expression, direction = (row.get(key) for key in
                                              ('factor_id', 'expression', 'direction'))
        if not isinstance(expression, str) or not expression.strip():
            raise ValueError('Candidate expression must be nonempty')
        try:
            expression_key = ast.dump(ast.parse(expression, mode='eval'))
        except SyntaxError as exc:
            raise ValueError('Invalid candidate expression') from exc
        expected_id = 'ngp_' + _sha(expression.encode('utf-8'))[:16]
        if identifier != expected_id:
            raise ValueError('Candidate ID does not match its expression hash')
        if type(direction) is not int or direction not in (-1, 1):
            raise ValueError('Candidate direction must be integer -1 or 1')
        if identifier in identifiers or expression_key in expressions:
            raise ValueError('Duplicate candidate ID or expression')
        identifiers.add(identifier)
        expressions.add(expression_key)
        definition_raw, definition_source = _read_source(output, f'library/{identifier}.toml')
        definition = tomllib.loads(definition_raw.decode('utf-8'))
        family = definition.get('family')
        if not isinstance(family, str) or not family.strip() or family != family.strip():
            raise ValueError('Candidate family must be nonempty')
        if (definition.get('id') != identifier or definition.get('expr') != expression
                or type(definition.get('direction')) is not int
                or definition['direction'] != direction
                or ('family' in row and row['family'] != family)):
            raise ValueError('Exported candidate definition does not match search.json')
        candidate = {'id': identifier, 'expression': expression, 'direction': direction, 'family': family}
        candidates.append({**candidate, 'candidate_sha256': _sha(_canonical(candidate))})
        definitions.append(definition_source)
    candidates.sort(key=lambda row: row['id'])
    definitions.sort(key=lambda row: row['path'])
    return {'schema_version': 'candidate_freeze_v1', 'search_output': str(output.resolve()),
            'auto_trade': False, 'forward_not_before': forward_not_before.isoformat(),
            'forward_start_rule': _FORWARD_RULE, 'candidates': candidates,
            'candidate_set_sha256': _sha(_canonical(candidates)),
            'sources': {'search': search_source, 'contract': contract_source, 'definitions': definitions}}


def _validate_receipt(receipt: dict) -> None:
    if not isinstance(receipt, dict):
        raise ValueError('Invalid candidate freeze receipt')
    payload = {key: value for key, value in receipt.items() if key != 'receipt_sha256'}
    if receipt.get('receipt_sha256') != _sha(_canonical(payload)):
        raise ValueError('Candidate freeze receipt checksum differs')
    try:
        frozen = dt.datetime.fromisoformat(receipt['frozen_at_utc'].replace('Z', '+00:00'))
        local_date = dt.date.fromisoformat(receipt['frozen_local_date'])
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise ValueError('Invalid candidate freeze timestamp') from exc
    if (frozen.utcoffset() != dt.timedelta(0) or receipt.get('freeze_timezone') != 'Asia/Shanghai'
            or frozen.astimezone(_LOCAL_TIMEZONE).date() != local_date):
        raise ValueError('Candidate freeze UTC/local dates disagree')


def _load_matching(path: Path, identity: dict) -> dict:
    receipt = json.loads(path.read_text(encoding='utf-8'))
    _validate_receipt(receipt)
    dynamic = {'frozen_at_utc', 'frozen_local_date', 'freeze_timezone', 'receipt_sha256'}
    if {key: value for key, value in receipt.items() if key not in dynamic} != identity:
        raise ValueError('Candidate freeze differs from current candidates, sources or forward bound')
    return receipt


def _sources_unchanged(output: Path, identity: dict) -> None:
    sources = identity['sources']
    for source in [sources['search'], sources['contract'], *sources['definitions']]:
        _, current = _read_source(output, source['path'])
        if current != source:
            raise ValueError('Candidate freeze sources changed before publication')


def _publish_no_clobber(path: Path, raw: bytes) -> bool:
    """Publish a complete fsynced file by atomic hard link; never overwrite the winner."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.candidate_freeze.',
                                         suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
            return True
        except FileExistsError:
            return False
        except OSError as exc:
            raise OSError('Atomic no-clobber candidate freeze publication failed') from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def freeze_completed_search(output: Path, *, receipt_path: Path | None = None,
                            forward_not_before: dt.date = FORWARD_NOT_BEFORE) -> dict:
    """Explicitly freeze saved exports now; replay returns the unchanged original receipt.

    No caller-provided timestamp or file mtime can set the freeze date. For an existing
    active batch, pass an external receipt_path to keep its N2 directory read-only.
    """
    output = Path(output)
    path = Path(receipt_path) if receipt_path is not None else output / 'candidate_freeze.json'
    identity = _identity(output, forward_not_before)
    if path.exists():
        return _load_matching(path, identity)
    now = _utc_now()
    if now.utcoffset() != dt.timedelta(0):
        raise ValueError('Freeze clock must report timezone-aware UTC')
    receipt = {**identity, 'frozen_at_utc': now.isoformat().replace('+00:00', 'Z'),
               'frozen_local_date': now.astimezone(_LOCAL_TIMEZONE).date().isoformat(),
               'freeze_timezone': 'Asia/Shanghai'}
    receipt['receipt_sha256'] = _sha(_canonical(receipt))
    _sources_unchanged(output, identity)
    _publish_no_clobber(path, json.dumps(receipt, ensure_ascii=False, indent=2).encode('utf-8'))
    return _load_matching(path, identity)


def load_candidate_freeze(output: Path, *, receipt_path: Path | None = None) -> dict:
    """Validate an existing receipt against current saved sources without creating files."""
    output = Path(output)
    path = Path(receipt_path) if receipt_path is not None else output / 'candidate_freeze.json'
    receipt = json.loads(path.read_text(encoding='utf-8'))
    _validate_receipt(receipt)
    identity = _identity(output, dt.date.fromisoformat(receipt['forward_not_before']))
    return _load_matching(path, identity)
