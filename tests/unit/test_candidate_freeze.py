"""Freeze durability checks use tiny synthetic exports, never production GP or labels."""
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import threading

import pytest

from quant.research import candidate_freeze as module


def export(root: Path, *, expression='pit_roa_ttm', direction=1, family='nightly_synthetic'):
    root.mkdir(parents=True, exist_ok=True)
    identifier = 'ngp_' + hashlib.sha256(expression.encode()).hexdigest()[:16]
    candidate = {'factor_id': identifier, 'expression': expression, 'direction': direction}
    (root / 'search.json').write_text(json.dumps({'candidates': [candidate], 'trials': []}))
    (root / 'search_contract.json').write_text(json.dumps({
        'objective': 'predictive_priority_v2', 'config': {'auto_trade': False, 'seed': 20260919}}))
    library = root / 'library'
    library.mkdir(exist_ok=True)
    definition = {'id': identifier, 'expr': expression, 'direction': direction, 'family': family}
    (library / f'{identifier}.toml').write_text(''.join(
        f'{key} = {json.dumps(value)}\n' for key, value in definition.items()))
    return candidate


def test_first_freeze_uses_actual_now_not_old_mtime_and_supports_external_path(tmp_path):
    root = tmp_path / 'N2'
    candidate = export(root)
    for path in root.rglob('*'):
        if path.is_file():
            os.utime(path, (946684800, 946684800))
    before = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
    target = tmp_path / 'evidence' / 'candidate_freeze.json'
    start = dt.datetime.now(dt.timezone.utc)
    receipt = module.freeze_completed_search(root, receipt_path=target)
    end = dt.datetime.now(dt.timezone.utc)
    observed = dt.datetime.fromisoformat(receipt['frozen_at_utc'].replace('Z', '+00:00'))
    assert start <= observed <= end
    assert receipt['frozen_local_date'] == observed.astimezone(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
    assert receipt['forward_not_before'] == '2026-09-21'
    assert 'next_trading_day' not in receipt and receipt['auto_trade'] is False
    assert receipt['candidates'][0]['id'] == candidate['factor_id']
    assert receipt['candidates'][0]['family'] == 'nightly_synthetic'
    assert not (root / 'candidate_freeze.json').exists()
    assert before == {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
    for item in [receipt['sources']['search'], receipt['sources']['contract'], *receipt['sources']['definitions']]:
        assert item['sha256'] == hashlib.sha256((root / item['path']).read_bytes()).hexdigest()
    assert module.load_candidate_freeze(root, receipt_path=target) == receipt


def test_replay_preserves_receipt_bytes_time_and_mtime_even_if_sources_touched(tmp_path, monkeypatch):
    export(tmp_path)
    first = module.freeze_completed_search(tmp_path)
    path = tmp_path / 'candidate_freeze.json'
    before = path.read_bytes(), path.stat().st_mtime_ns
    os.utime(tmp_path / 'search.json', (1700000000, 1700000000))
    monkeypatch.setattr(module, '_utc_now', lambda: pytest.fail('Reuse must not create a new freeze time'))
    assert module.freeze_completed_search(tmp_path) == first
    assert module.load_candidate_freeze(tmp_path) == first
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


@pytest.mark.parametrize('change', ['search', 'contract', 'direction', 'family', 'expression'])
def test_changed_candidate_or_source_is_rejected_without_overwriting_receipt(tmp_path, change):
    item = export(tmp_path)
    module.freeze_completed_search(tmp_path)
    path = tmp_path / 'candidate_freeze.json'
    before = path.read_bytes(), path.stat().st_mtime_ns
    if change == 'search':
        content = json.loads((tmp_path / 'search.json').read_text())
        content['trials'].append({'changed': True})
        (tmp_path / 'search.json').write_text(json.dumps(content))
    elif change == 'contract':
        contract = json.loads((tmp_path / 'search_contract.json').read_text())
        contract['config']['seed'] += 1
        (tmp_path / 'search_contract.json').write_text(json.dumps(contract))
    else:
        export(tmp_path, expression='pit_roe_ttm' if change == 'expression' else item['expression'],
               direction=-1 if change == 'direction' else 1,
               family='nightly_changed' if change == 'family' else 'nightly_synthetic')
    for operation in (module.freeze_completed_search, module.load_candidate_freeze):
        with pytest.raises(ValueError, match='differs'):
            operation(tmp_path)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


@pytest.mark.parametrize('change', ['empty', 'duplicate', 'id', 'direction_zero', 'direction_bool',
                                   'blank_expression', 'blank_family', 'definition'])
def test_invalid_export_cannot_create_a_receipt(tmp_path, change):
    item = export(tmp_path)
    source = tmp_path / 'search.json'
    search = json.loads(source.read_text())
    row = search['candidates'][0]
    if change == 'empty':
        search['candidates'] = []
    elif change == 'duplicate':
        search['candidates'].append(dict(row))
    elif change == 'id':
        row['factor_id'] = '../../escape'
    elif change == 'direction_zero':
        row['direction'] = 0
    elif change == 'direction_bool':
        row['direction'] = True
    elif change == 'blank_expression':
        row['expression'] = ' '
    elif change == 'blank_family':
        export(tmp_path, family='')
    else:
        definition = tmp_path / 'library' / f"{item['factor_id']}.toml"
        definition.write_text(definition.read_text().replace('direction = 1', 'direction = -1'))
    source.write_text(json.dumps(search))
    with pytest.raises(ValueError):
        module.freeze_completed_search(tmp_path)
    assert not (tmp_path / 'candidate_freeze.json').exists()


def test_loading_absent_receipt_does_not_create_one(tmp_path):
    export(tmp_path)
    with pytest.raises(FileNotFoundError):
        module.load_candidate_freeze(tmp_path)
    assert not (tmp_path / 'candidate_freeze.json').exists()


def test_receipt_tampering_is_not_accepted(tmp_path):
    export(tmp_path)
    module.freeze_completed_search(tmp_path)
    path = tmp_path / 'candidate_freeze.json'
    receipt = json.loads(path.read_text())
    receipt['frozen_at_utc'] = '2000-01-01T00:00:00Z'
    path.write_text(json.dumps(receipt))
    for operation in (module.freeze_completed_search, module.load_candidate_freeze):
        with pytest.raises(ValueError, match='checksum'):
            operation(tmp_path)


def test_concurrent_creators_publish_one_complete_unchanged_receipt(tmp_path, monkeypatch):
    export(tmp_path)
    barrier = threading.Barrier(2)
    real_publish = module._publish_no_clobber

    def together(path, raw):
        barrier.wait(timeout=5)
        return real_publish(path, raw)

    monkeypatch.setattr(module, '_publish_no_clobber', together)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(module.freeze_completed_search, tmp_path) for _ in range(2)]
        receipts = [future.result(timeout=10) for future in futures]
    assert receipts[0] == receipts[1] == module.load_candidate_freeze(tmp_path)
    assert not list(tmp_path.glob('.candidate_freeze.*.tmp'))


def test_publication_failure_does_not_leave_partial_receipt(tmp_path, monkeypatch):
    export(tmp_path)

    def unavailable(*args):
        raise OSError('Synthetic hardlink failure')

    monkeypatch.setattr(module.os, 'link', unavailable)
    with pytest.raises(OSError, match='no-clobber'):
        module.freeze_completed_search(tmp_path)
    assert not (tmp_path / 'candidate_freeze.json').exists()
    assert not list(tmp_path.glob('.candidate_freeze.*.tmp'))


def test_utc_to_local_rollover_does_not_guess_a_session(tmp_path, monkeypatch):
    export(tmp_path)
    monkeypatch.setattr(module, '_utc_now', lambda: dt.datetime(2026, 9, 19, 16, 30, tzinfo=dt.timezone.utc))
    receipt = module.freeze_completed_search(tmp_path)
    assert receipt['frozen_local_date'] == '2026-09-20'
    assert receipt['forward_not_before'] == '2026-09-21'
    assert 'daily/calendar' in receipt['forward_start_rule']
    with pytest.raises(ValueError, match='lower bound'):
        module.freeze_completed_search(tmp_path, forward_not_before=dt.date(2026, 9, 20))


def test_source_changed_before_publication_is_rejected(tmp_path, monkeypatch):
    export(tmp_path)
    real_clock = module._utc_now

    def change_source():
        (tmp_path / 'search.json').write_text('{}')
        return real_clock()

    monkeypatch.setattr(module, '_utc_now', change_source)
    with pytest.raises(ValueError, match='sources changed'):
        module.freeze_completed_search(tmp_path)
    assert not (tmp_path / 'candidate_freeze.json').exists()
